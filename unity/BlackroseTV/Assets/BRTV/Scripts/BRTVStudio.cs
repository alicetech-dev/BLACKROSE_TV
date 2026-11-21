// BlackRose TV Studio — la app (escena Studio.unity). Interfaz en UI Toolkit (Assets/BRTV/UI/Studio.uxml + Studio.uss,
// editables en el UI Builder) sobre los sets de ESTUDIO 2049. El servidor del Studio (python -m studio.servidor, :8840)
// guarda el proyecto, el reparto y la IA; esta app lo consulta por HTTP y escucha /ws.
//
//   Tab / F1   esconder o mostrar la interfaz (para grabar limpio)
//
// Config opcional brtv_studio.json junto al ejecutable (o al proyecto en el editor): {"studio_url": "http://127.0.0.1:8840"}
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UIElements;

public class BRTVStudio : MonoBehaviour
{
    public BRTVEstacion estacion;
    public UIDocument ui;
    public string studioUrl = "http://127.0.0.1:8840";

    // el servidor guarda los puestos de la escena como p1/p2; en los sets de Unity son los puestos de Joy y de Kuroki
    static readonly string[] PUESTOS = { "p1", "p2" };

    class Ficha { public string id, nombre, vrm; }
    readonly List<Ficha> reparto = new List<Ficha>();
    string carpetaReparto = "";
    readonly Dictionary<string, string> asignado = new Dictionary<string, string>();   // puesto → url /reparto/x.vrm
    readonly Dictionary<string, string> nombres = new Dictionary<string, string>();
    bool conectado;
    VisualElement raiz;
    CancellationTokenSource cts = new CancellationTokenSource();
    readonly System.Collections.Concurrent.ConcurrentQueue<Action> cola = new System.Collections.Concurrent.ConcurrentQueue<Action>();

    // ------------------------------------------------------------------ arranque
    void Awake()
    {
        var ruta = Path.Combine(Path.GetDirectoryName(Application.dataPath) ?? ".", "brtv_studio.json");
        if (File.Exists(ruta) && MiniJson.Parse(File.ReadAllText(ruta)) is Dictionary<string, object> d && d.TryGetValue("studio_url", out var u) && u is string us)
            studioUrl = us.TrimEnd('/');
        if (estacion == null) estacion = FindObjectOfType<BRTVEstacion>();
        if (ui == null) ui = GetComponent<UIDocument>();
    }

    IEnumerator Start()
    {
        yield return null;                                   // BRTVEstacion.Start ya eligió el set
        raiz = ui.rootVisualElement;
        Pestanas();
        var guardado = PlayerPrefs.GetString("studio.set", "");
        if (guardado != "" && estacion.Sets.Any(s => s.nombre == guardado)) estacion.IrASet(guardado);
        PintarSets(); PintarCamaras();
        Q<Button>("copiar_web").clicked += () => Application.OpenURL(studioUrl + "/estudio#estacion");
        yield return Conectar();
        _ = Escuchar();
    }

    void OnDestroy() => cts.Cancel();

    T Q<T>(string n) where T : VisualElement => raiz.Q<T>(n);

    void Update()
    {
        while (cola.TryDequeue(out var a)) a();
        if (Input.GetKeyDown(KeyCode.Tab) || Input.GetKeyDown(KeyCode.F1))
            raiz.style.display = raiz.style.display == DisplayStyle.None ? DisplayStyle.Flex : DisplayStyle.None;
        PintarAire();
    }

    // ------------------------------------------------------------------ pestañas
    void Pestanas()
    {
        foreach (var b in raiz.Query<Button>(className: "tab").ToList())
        {
            var id = b.name.Replace("tab_", "");
            b.clicked += () => IrA(id);
        }
        IrA(PlayerPrefs.GetString("studio.tab", "set"));
    }

    void IrA(string id)
    {
        if (Q<VisualElement>("pantalla_" + id) == null) id = "set";
        foreach (var b in raiz.Query<Button>(className: "tab").ToList()) b.EnableInClassList("activo", b.name == "tab_" + id);
        foreach (var p in raiz.Query<VisualElement>(className: "pantalla").ToList()) p.style.display = p.name == "pantalla_" + id ? DisplayStyle.Flex : DisplayStyle.None;
        PlayerPrefs.SetString("studio.tab", id);
    }

    // ------------------------------------------------------------------ SET: sets, cámaras, quién está en el set
    void PintarSets()
    {
        var caja = Q<VisualElement>("sets"); caja.Clear();
        foreach (var s in estacion.Sets)
        {
            var b = new Button(() => { estacion.IrASet(s.nombre); PlayerPrefs.SetString("studio.set", s.nombre); PintarSets(); PintarCamaras(); }) { text = s.titulo };
            b.AddToClassList("set");
            b.EnableInClassList("activo", estacion.SetActual == s);
            caja.Add(b);
        }
    }

    void PintarCamaras()
    {
        var caja = Q<VisualElement>("camaras"); caja.Clear();
        var set = estacion.SetActual; if (set == null) return;
        void Boton(string id, string texto, string sub)
        {
            var b = new Button(() => { estacion.Camara(id); PintarCamaras(); }); b.AddToClassList("cam"); b.name = "cam_" + id;
            b.Add(new Label(texto) { name = "titulo" }); b.Add(new Label(sub) { name = "sub" });
            b.EnableInClassList("activo", estacion.CamaraFija == id);
            caja.Add(b);
        }
        Boton("auto", "Automático", "⟳ corta solo");
        foreach (var p in set.planos.Where(p => p != null))
            Boton(p.name, Bonito(p.name), p.foco != "" ? "primer plano · " + (p.foco == "joy" ? "puesto 1" : "puesto 2") : "plano");
    }

    string ultimoAire = null;
    void PintarAire()
    {
        if (raiz == null || estacion == null || estacion.PlanoActual == ultimoAire) return;
        ultimoAire = estacion.PlanoActual;
        var chip = Q<Label>("chip_aire"); if (chip != null) chip.text = "● " + Bonito(ultimoAire).ToUpperInvariant();
        foreach (var b in raiz.Query<Button>(className: "cam").ToList()) b.EnableInClassList("aire", b.name == "cam_" + ultimoAire);
    }

    static string Bonito(string s) => string.IsNullOrEmpty(s) ? "—" : char.ToUpper(s[0]) + s.Substring(1).Replace('_', ' ');

    void PintarPuestos()
    {
        var caja = Q<VisualElement>("puestos"); caja.Clear();
        var opciones = new List<string> { "— vacío —" }; opciones.AddRange(reparto.Select(f => f.nombre));
        for (int i = 0; i < PUESTOS.Length; i++)
        {
            var p = PUESTOS[i];
            var fila = new VisualElement(); fila.AddToClassList("puesto");
            fila.Add(new Label($"Puesto {i + 1}") { name = "etq" });
            asignado.TryGetValue(p, out var url);
            var actual = reparto.FirstOrDefault(f => f.vrm == url);
            var dd = new DropdownField(opciones, actual != null ? reparto.IndexOf(actual) + 1 : 0);
            dd.RegisterValueChangedCallback(ev =>
            {
                var f = reparto.FirstOrDefault(x => x.nombre == ev.newValue);
                StartCoroutine(Asignar(p, f));
            });
            fila.Add(dd); caja.Add(fila);
        }
        Q<Label>("reparto_vacio").style.display = reparto.Count == 0 ? DisplayStyle.Flex : DisplayStyle.None;
    }

    IEnumerator Asignar(string puesto, Ficha f)
    {
        asignado[puesto] = f?.vrm; nombres[puesto] = f?.nombre ?? "";
        AplicarVRM(puesto);
        // el servidor guarda la escena completa de reparto (lista de puestos)
        var lista = PUESTOS.Select(p => "{\"id\":\"" + p + "\",\"nombre\":\"" + MiniJson.Esc(nombres.TryGetValue(p, out var n) ? n : "") + "\",\"vrm\":" +
                                        (asignado.TryGetValue(p, out var u) && !string.IsNullOrEmpty(u) ? "\"" + MiniJson.Esc(u) + "\"" : "null") +
                                        ",\"pos\":\"" + (p == "p1" ? "mesa_izq" : "mesa_der") + "\"}");
        yield return Pedir("POST", "/api/escena", "{\"reparto\":[" + string.Join(",", lista) + "]}", null);
    }

    void AplicarVRM(string puesto)
    {
        var doll = puesto == "p1" ? estacion.joy : estacion.kuroki;
        if (doll == null) return;
        asignado.TryGetValue(puesto, out var url);
        var ruta = string.IsNullOrEmpty(url) ? "" : Path.Combine(carpetaReparto, Path.GetFileName(url));
        doll.Recargar(ruta);
    }

    // ------------------------------------------------------------------ servidor
    IEnumerator Conectar()
    {
        Estado(false, "conectando…");
        Dictionary<string, object> info = null, escena = null; List<object> lista = null;
        yield return Pedir("GET", "/api/info", null, t => info = MiniJson.Parse(t) as Dictionary<string, object>);
        if (info == null) { Estado(false, "sin servidor — corre ./studio.sh start"); yield return new WaitForSeconds(3); StartCoroutine(Conectar()); yield break; }
        carpetaReparto = info.TryGetValue("reparto", out var r) ? r as string : "";
        yield return Pedir("GET", "/api/reparto", null, t => lista = MiniJson.Parse(t) as List<object>);
        yield return Pedir("GET", "/api/escena", null, t => escena = MiniJson.Parse(t) as Dictionary<string, object>);
        reparto.Clear();
        foreach (var o in lista ?? new List<object>())
            if (o is Dictionary<string, object> d)
                reparto.Add(new Ficha { id = d["id"] as string, nombre = d.TryGetValue("nombre", out var n) ? n as string : d["id"] as string, vrm = d["vrm"] as string });
        if (escena != null && escena.TryGetValue("reparto", out var er) && er is List<object> el)
            foreach (var o in el)
                if (o is Dictionary<string, object> d && d["id"] is string pid && PUESTOS.Contains(pid))
                {
                    asignado[pid] = d.TryGetValue("vrm", out var v) ? v as string : null;
                    nombres[pid] = d.TryGetValue("nombre", out var nn) ? nn as string : "";
                }
        foreach (var p in PUESTOS) AplicarVRM(p);
        PintarPuestos();
        Estado(true, "conectado");
    }

    void Estado(bool ok, string texto)
    {
        conectado = ok;
        var e = Q<Label>("estado"); if (e == null) return;
        e.text = "● " + texto; e.EnableInClassList("ok", ok);
    }

    IEnumerator Pedir(string metodo, string ruta, string json, Action<string> alTerminar)
    {
        using (var w = new UnityWebRequest(studioUrl + ruta, metodo))
        {
            w.downloadHandler = new DownloadHandlerBuffer();
            if (json != null) { w.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json)); w.SetRequestHeader("Content-Type", "application/json"); }
            w.timeout = 5;
            yield return w.SendWebRequest();
            if (w.result == UnityWebRequest.Result.Success) alTerminar?.Invoke(w.downloadHandler.text);
            else Debug.LogWarning("[Studio] " + metodo + " " + ruta + ": " + w.error);
        }
    }

    // /ws del servidor: {"t":"habla","id":"p1","on":true} → primer plano de ese puesto; {"t":"escena"} → recargar reparto
    async Task Escuchar()
    {
        var url = studioUrl.Replace("http://", "ws://").Replace("https://", "wss://") + "/ws";
        var buf = new byte[1 << 16];
        while (!cts.IsCancellationRequested)
        {
            try
            {
                using (var ws = new ClientWebSocket())
                {
                    await ws.ConnectAsync(new Uri(url), cts.Token);
                    var sb = new StringBuilder();
                    while (ws.State == WebSocketState.Open)
                    {
                        var r = await ws.ReceiveAsync(new ArraySegment<byte>(buf), cts.Token);
                        if (r.MessageType == WebSocketMessageType.Close) break;
                        sb.Append(Encoding.UTF8.GetString(buf, 0, r.Count)); if (!r.EndOfMessage) continue;
                        var m = MiniJson.Parse(sb.ToString()) as Dictionary<string, object>; sb.Clear();
                        if (m == null || !(m.TryGetValue("t", out var t) && t is string tipo)) continue;
                        if (tipo == "habla" && m.TryGetValue("id", out var id) && id is string pid)
                        {
                            bool on = m.TryGetValue("on", out var o) && o is bool b && b;
                            cola.Enqueue(() => estacion.Hablar(pid == "p1" ? "joy" : "kuroki", on));
                        }
                    }
                }
            }
            catch (Exception) { }
            try { await Task.Delay(3000, cts.Token); } catch { }
        }
    }
}
