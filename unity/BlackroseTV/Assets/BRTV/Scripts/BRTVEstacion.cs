// BlackRose TV 2049 — la estación. Un solo programa de cámara que corta entre los planos del set activo, mueve a Joy y Kuroki
// al puesto de cada set y escucha:
//   · el director de dolls (ws :8780, `frase`/`fin`) → primer plano de quien habla
//   · su API HTTP local (por defecto :8836):
//       GET /api/estado                      → set, plano, lista de sets
//       GET /api/set?n=deportes              → cambia de set (corte)
//       GET /api/cam?n=auto|<plano>          → plano fijo o automático
//       GET /api/titulares?t=uno|dos|tres    → titulares de las holopantallas del núcleo y el zócalo
//       GET /api/medio?img=/ruta.jpg         → foto en las pantallas de medios (vacío = vuelve el ident)
// Config: brtv.json junto al ejecutable (o -config ruta). Modo prueba: -captura DIR (foto de cada plano y sale).
using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using TMPro;
using UnityEngine;

public class BRTVEstacion : MonoBehaviour
{
    public Camera cam;
    public BRTVDoll joy, kuroki;
    public float planoMin = 8, planoMax = 14;

    BRTVSet[] sets; BRTVSet set; BRTVPlano plano; string camFija = "auto";
    float proximoCorte; Vector3 camBase; Quaternion camRot; float camT;
    string habla; float hablaHasta;
    readonly ConcurrentQueue<Action> cola = new ConcurrentQueue<Action>();
    HttpListener http; CancellationTokenSource cts = new CancellationTokenSource();
    Dictionary<string, object> cfg = new Dictionary<string, object>();
    Material medioMat; readonly List<(Renderer r, Material m)> medios = new List<(Renderer, Material)>();

    static string Arg(string n) { var a = Environment.GetCommandLineArgs(); int i = Array.IndexOf(a, n); return i >= 0 && i + 1 < a.Length ? a[i + 1] : null; }
    string C(string k, string def) => cfg.TryGetValue(k, out var v) && v is string s ? s : def;

    void Awake()
    {
        QualitySettings.pixelLightCount = 10;
        var ruta = Arg("-config") ?? Path.Combine(Path.GetDirectoryName(Application.dataPath) ?? ".", "brtv.json");
        if (File.Exists(ruta) && MiniJson.Parse(File.ReadAllText(ruta)) is Dictionary<string, object> d) cfg = d;
        int fps = cfg.TryGetValue("fps", out var f) && f is double fd ? (int)fd : 30;
        Application.targetFrameRate = fps; QualitySettings.vSyncCount = 0;
        // texturas a la mitad (o ¼ con 2): la AMD usa la RAM del sistema y la PC va justa (oomd mató al 4B con 1,2 GB de texturas)
        QualitySettings.masterTextureLimit = cfg.TryGetValue("texturas", out var tl) && tl is double tld ? (int)tld : 1;

        // VRM de las conductoras y del personal
        if (cfg.TryGetValue("dolls", out var dl) && dl is Dictionary<string, object> dolls)
        {
            void Doll(BRTVDoll b, string k)
            {
                if (b == null || !dolls.TryGetValue(k, out var o) || !(o is Dictionary<string, object> dd)) return;
                if (dd.TryGetValue("vrm", out var v)) b.vrmPath = v as string;
                if (dd.TryGetValue("ws", out var w)) b.wsUrl = w as string;
            }
            Doll(joy, "joy"); Doll(kuroki, "kuroki");
        }
        var personal = (cfg.TryGetValue("personal", out var p) && p is List<object> pl) ? pl.OfType<string>().Where(File.Exists).ToList() : new List<string>();
        int i = 0;
        foreach (var b in FindObjectsOfType<BRTVDoll>(true))
        {
            if (b == joy || b == kuroki) continue;
            if (personal.Count == 0) { b.gameObject.SetActive(false); continue; }
            b.vrmPath = personal[i++ % personal.Count];
        }
        sets = FindObjectsOfType<BRTVSet>(true).OrderBy(s => s.transform.GetSiblingIndex()).ToArray();
        foreach (var r in FindObjectsOfType<Renderer>(true))
            if (r.name.StartsWith("Pantalla_Medio")) medios.Add((r, r.sharedMaterial));
    }

    void Start()
    {
        IrASet(Arg("-set") ?? C("set", "noticiario"));
        _ = Director(C("director", "ws://127.0.0.1:8780/ws"));
        int puerto = cfg.TryGetValue("puerto", out var po) && po is double pd ? (int)pd : 8836;
        if (Arg("-captura") == null) Servir(puerto);
        if (Arg("-captura") != null) StartCoroutine(Captura(Arg("-captura")));
        // salida al aire (ffmpeg → UDP → OBS): config "salida" o -salida URL
        var sal = cfg.TryGetValue("salida", out var so) ? so as Dictionary<string, object> : null;
        if (Arg("-captura") == null && (sal != null || Arg("-salida") != null))
        {
            Application.runInBackground = true;
            var s = gameObject.AddComponent<BRTVSalida>(); s.cam = cam; s.fps = Application.targetFrameRate;
            int N(string k, int def) => sal != null && sal.TryGetValue(k, out var v) && v is double d ? (int)d : def;
            s.ancho = N("ancho", 1280); s.alto = N("alto", 720);
            if (sal != null && sal.TryGetValue("url", out var u) && u is string us) s.url = us;
            if (Arg("-salida") != null) s.url = Arg("-salida");
            if (sal != null && sal.TryGetValue("voltear", out var vf) && vf is bool vb) s.voltear = vb;
            if (sal != null && sal.TryGetValue("ffmpeg", out var fa) && fa is string fs) s.ffArgs = fs;
        }
    }

    void OnDestroy() { cts.Cancel(); try { http?.Stop(); } catch { } }

    // ------------------------------------------------------------------ sets y planos
    public void IrASet(string n)
    {
        var s = sets.FirstOrDefault(x => x.nombre == n) ?? sets.FirstOrDefault(x => x.nombre == "noticiario") ?? sets[0];
        set = s;
        Poner(joy, s.puestoJoy, s); Poner(kuroki, s.puestoKuroki, s);
        plano = null; Cortar();
        Debug.Log("[BRTV] set " + s.nombre);
    }

    void Poner(BRTVDoll d, Transform puesto, BRTVSet s)
    {
        if (d == null) return;
        d.gameObject.SetActive(puesto != null);
        if (puesto == null) return;
        d.transform.SetPositionAndRotation(puesto.position, puesto.rotation);
        d.sentada = s.sentadas; d.asiento = s.asiento;
    }

    void Cortar()
    {
        BRTVPlano sig = null;
        if (camFija != "auto") sig = set.planos.FirstOrDefault(x => x.name == camFija);
        if (sig == null && habla != null && Time.time < hablaHasta)
        {
            var cand = set.planos.Where(x => x.foco == habla).ToArray();
            if (cand.Length > 0 && UnityEngine.Random.value < 0.85f) sig = cand[UnityEngine.Random.Range(0, cand.Length)];
        }
        if (sig == null)
        {
            var cand = set.planos.Where(x => x != plano && (x.foco == "" || UnityEngine.Random.value < 0.3f)).ToArray();
            if (cand.Length == 0) cand = set.planos;
            sig = cand[UnityEngine.Random.Range(0, cand.Length)];
        }
        Aplicar(sig);
        proximoCorte = Time.time + UnityEngine.Random.Range(planoMin, planoMax);
    }

    void Aplicar(BRTVPlano pl)
    {
        plano = pl; camBase = pl.transform.position; camRot = pl.transform.rotation; camT = 0;
        cam.transform.SetPositionAndRotation(camBase, camRot); cam.fieldOfView = pl.fov;
    }

    // el personal de los otros sets se apaga (ahorra skinning); hasta que todas cargan quedan prendidas
    bool personalListo; BRTVDoll[] personal;
    void Personal()
    {
        if (personal == null) personal = FindObjectsOfType<BRTVDoll>(true).Where(d => d != joy && d != kuroki && !string.IsNullOrEmpty(d.vrmPath)).ToArray();
        if (!personalListo) { if (Time.time < 60 && personal.Any(d => d.gameObject.activeInHierarchy && !d.Lista)) return; personalListo = true; }
        var sala = set.transform.parent;
        foreach (var d in personal) { bool v = d.transform.IsChildOf(sala); if (d.gameObject.activeSelf != v) d.gameObject.SetActive(v); }
    }

    void Update()
    {
        while (cola.TryDequeue(out var a)) { try { a(); } catch (Exception e) { Debug.LogException(e); } }
        Personal();
        if (plano == null) return;
        camT += Time.deltaTime;
        var der = plano.transform.right * Mathf.Sin(camT * 0.08f) * plano.deriva + plano.transform.up * Mathf.Sin(camT * 0.05f) * plano.deriva * 0.25f;
        // 20-nov: acercamiento lento en cada plano (más en el primer plano de quien habla): se siente cámara de TV, no foto fija
        float acerca = Mathf.SmoothStep(0, 1, Mathf.Clamp01(camT / 11f));
        bool primer = plano.foco != "" && plano.foco == habla;
        cam.fieldOfView = Mathf.Lerp(plano.fov, plano.fov * (primer ? 0.72f : 0.88f), acerca);
        cam.transform.SetPositionAndRotation(camBase + der + plano.transform.forward * acerca * (primer ? 0.25f : 0.6f), camRot);
        if (Arg("-captura") == null && Time.time > proximoCorte) Cortar();
    }

    // ------------------------------------------------------------------ director de dolls: quién habla
    async Task Director(string url)
    {
        var buf = new byte[1 << 15];
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
                        if (m == null || !m.TryGetValue("doll", out var dObj) || !(dObj is string doll) || (doll != "joy" && doll != "kuroki")) continue;
                        var tipo = m.TryGetValue("type", out var t) ? t as string : "";
                        if (tipo == "frase") cola.Enqueue(() => { bool nueva = habla != doll; habla = doll; hablaHasta = Time.time + 60; if (nueva && camFija == "auto" && Time.time > proximoCorte - planoMax + 2.5f) Cortar(); });
                        else if (tipo == "fin") cola.Enqueue(() => { if (habla == doll) hablaHasta = Time.time + 2.5f; });
                    }
                }
            }
            catch (Exception) { }
            try { await Task.Delay(3000, cts.Token); } catch { }
        }
    }

    // ------------------------------------------------------------------ API HTTP
    void Servir(int puerto)
    {
        try { http = new HttpListener(); http.Prefixes.Add($"http://127.0.0.1:{puerto}/"); http.Start(); }
        catch (Exception e) { Debug.LogError("[BRTV] no pude abrir :" + puerto + " " + e.Message); return; }
        Task.Run(async () =>
        {
            while (!cts.IsCancellationRequested && http.IsListening)
            {
                HttpListenerContext ctx;
                try { ctx = await http.GetContextAsync(); } catch { break; }
                _ = Task.Run(() => Atender(ctx));
            }
        });
    }

    void Atender(HttpListenerContext ctx)
    {
        string resp = "{\"ok\":true}";
        try
        {
            var path = ctx.Request.Url.AbsolutePath; var q = ctx.Request.QueryString;
            var listo = new ManualResetEventSlim();
            switch (path)
            {
                case "/api/set": { var n = q["n"]; cola.Enqueue(() => { IrASet(n); listo.Set(); }); listo.Wait(2000); break; }
                case "/api/cam": { var n = q["n"] ?? "auto"; cola.Enqueue(() => { camFija = n; Cortar(); listo.Set(); }); listo.Wait(2000); break; }
                case "/api/titulares": { var t = (q["t"] ?? "").Split('|'); cola.Enqueue(() => Titulares(t)); break; }
                case "/api/medio": { var img = q["img"] ?? ""; cola.Enqueue(() => Medio(img)); break; }
                case "/api/estado": default:
                    {
                        string est = null;
                        cola.Enqueue(() =>
                        {
                            est = "{\"set\":\"" + set.nombre + "\",\"plano\":\"" + (plano ? plano.name : "") + "\",\"cam\":\"" + MiniJson.Esc(camFija) + "\",\"habla\":\"" + (habla ?? "") +
                                  "\",\"joy\":" + (joy && joy.Lista ? "true" : "false") + ",\"kuroki\":" + (kuroki && kuroki.Lista ? "true" : "false") +
                                  ",\"sets\":[" + string.Join(",", sets.Select(s => "{\"n\":\"" + s.nombre + "\",\"t\":\"" + MiniJson.Esc(s.titulo) + "\",\"planos\":[" + string.Join(",", s.planos.Select(p => "\"" + p.name + "\"")) + "]}")) + "]}";
                            listo.Set();
                        });
                        listo.Wait(2000); resp = est ?? "{}"; break;
                    }
            }
        }
        catch (Exception e) { resp = "{\"ok\":false,\"error\":\"" + MiniJson.Esc(e.Message) + "\"}"; }
        try
        {
            var b = Encoding.UTF8.GetBytes(resp);
            ctx.Response.ContentType = "application/json; charset=utf-8"; ctx.Response.AddHeader("Access-Control-Allow-Origin", "*");
            ctx.Response.OutputStream.Write(b, 0, b.Length); ctx.Response.Close();
        }
        catch { }
    }

    void Titulares(string[] t)
    {
        var l = t.Where(x => !string.IsNullOrWhiteSpace(x)).ToArray(); if (l.Length == 0) return;
        int i = 0;
        foreach (var tx in FindObjectsOfType<TextMeshPro>(true).Where(x => x.name.StartsWith("TXT_titular")).OrderBy(x => x.name))
            tx.text = l[i++ % l.Length].ToUpperInvariant();
        foreach (var r in FindObjectsOfType<BRTVRotador>(true).Where(x => x.name.StartsWith("TXT_zocalo")))
            r.Poner(l.Select(x => x.ToUpperInvariant()).ToArray());
    }

    void Medio(string img)
    {
        if (string.IsNullOrEmpty(img) || !File.Exists(img)) { foreach (var (r, m) in medios) r.sharedMaterial = m; return; }
        var tex = new Texture2D(2, 2); tex.LoadImage(File.ReadAllBytes(img));
        if (medioMat == null) medioMat = new Material(Shader.Find("Unlit/Texture"));
        if (medioMat.mainTexture) Destroy(medioMat.mainTexture);
        medioMat.mainTexture = tex;
        foreach (var (r, _) in medios) r.sharedMaterial = medioMat;
    }

    // ------------------------------------------------------------------ prueba: foto de cada plano
    IEnumerator Captura(string dir)
    {
        Directory.CreateDirectory(dir);
        float t0 = Time.time;
        while (Time.time - t0 < 60 && ((joy && !joy.Lista) || (kuroki && !kuroki.Lista) || FindObjectsOfType<BRTVDoll>().Any(d => !d.Lista))) yield return null;
        yield return new WaitForSeconds(2);
        var solo = Arg("-sets");
        var rt = new RenderTexture(1280, 720, 24, RenderTextureFormat.ARGB32); rt.antiAliasing = 4;
        var tex = new Texture2D(1280, 720, TextureFormat.RGB24, false);
        foreach (var s in sets)
        {
            if (solo != null && !solo.Split(',').Contains(s.nombre)) continue;
            IrASet(s.nombre);
            foreach (var p in s.planos)
            {
                Aplicar(p); yield return new WaitForSeconds(0.4f); yield return new WaitForEndOfFrame();
                cam.targetTexture = rt; cam.Render(); RenderTexture.active = rt;
                tex.ReadPixels(new Rect(0, 0, 1280, 720), 0, 0); tex.Apply(); cam.targetTexture = null; RenderTexture.active = null;
                File.WriteAllBytes(Path.Combine(dir, s.nombre + "__" + p.name + ".jpg"), tex.EncodeToJPG(88));
            }
        }
        Debug.Log("[BRTV] captura lista en " + dir);
        Application.Quit();
    }
}
