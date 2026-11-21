// BlackRose TV 2049 — una persona en el set: las conductoras (Joy y Kuroki, pose en vivo por el WebSocket de sus overlays,
// el mismo eco VMC que usa la sala 3D :8830) o el personal del canal (mismas VRM SFW con otro color de pelo, animación
// procedural: teclear, mirar pantallas, hablar por la holomesa). Los VRM se cargan en tiempo de ejecución con UniVRM
// (un archivo se lee una vez y se clona para cada copia).
using System;
using System.Collections.Generic;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UniGLTF;
using UnityEngine;
using VRM;
using VRMShaders;

public class BRTVDoll : MonoBehaviour
{
    public enum Modo { EnVivo, Tecleando, Holomesa, Parada, Camarografa }

    public string id = "";
    public string vrmPath = "";
    public string wsUrl = "";
    public Modo modo = Modo.EnVivo;
    public bool sentada;
    public float asiento = 0.48f;        // alto del asiento (m, local al padre)
    public float altura = 1.68f;
    public Color tintePelo = new Color(0, 0, 0, 0);   // a = 0 → sin cambio
    public float semilla;

    public bool Lista { get; private set; }
    public float UltimoCuadro { get; private set; } = -99;

    Animator anim; VRMBlendShapeProxy proxy; GameObject modelo;
    readonly Dictionary<HumanBodyBones, Transform> hueso = new Dictionary<HumanBodyBones, Transform>();
    Vector3 caderaRest; float caderaAlto; float parpado = 3;

    // ------------------------------------------------------------------ carga compartida
    static readonly Dictionary<string, Task<RuntimeGltfInstance>> cache = new Dictionary<string, Task<RuntimeGltfInstance>>();
    static Task<RuntimeGltfInstance> Cargar(string path)
    {
        if (!cache.TryGetValue(path, out var t))
        {
            t = VrmUtility.LoadAsync(path, new RuntimeOnlyAwaitCaller());
            cache[path] = t;
        }
        return t;
    }

    // texturas del VRM a DXT (¼ de memoria) y sin copia en RAM: la AMD usa la RAM del sistema y la PC va justa
    static readonly HashSet<Texture2D> aligeradas = new HashSet<Texture2D>();
    static void Aligerar(GameObject go)
    {
        int n = 0;
        foreach (var r in go.GetComponentsInChildren<Renderer>(true))
            foreach (var m in r.sharedMaterials)
            {
                if (m == null) continue;
                foreach (var prop in m.GetTexturePropertyNames())
                {
                    if (!(m.GetTexture(prop) is Texture2D t) || !t.isReadable || !aligeradas.Add(t)) continue;
                    try
                    {
                        if (t.format != TextureFormat.DXT1 && t.format != TextureFormat.DXT5 && t.width % 4 == 0 && t.height % 4 == 0) t.Compress(true);
                        t.Apply(false, true); n++;
                    }
                    catch (Exception e) { Debug.LogWarning("[BRTV] textura " + t.name + ": " + e.Message); }
                }
            }
        Debug.Log("[BRTV] " + go.name + ": " + n + " texturas aligeradas");
    }

    void Start() { semilla = semilla == 0 ? UnityEngine.Random.value * 100 : semilla; _ = Montar(); }

    /// <summary>Cambia el VRM en caliente (lo usa el Studio). Vacío = sin modelo.</summary>
    public void Recargar(string path)
    {
        if (path == vrmPath && (Lista || string.IsNullOrEmpty(path))) return;
        cts?.Cancel();
        Lista = false; hueso.Clear();
        if (modelo != null) Destroy(modelo);
        modelo = null; vrmPath = path ?? "";
        if (!string.IsNullOrEmpty(vrmPath)) _ = Montar();
    }

    async Task Montar()
    {
        var pedido = vrmPath;
        if (string.IsNullOrEmpty(vrmPath) || !System.IO.File.Exists(vrmPath)) { Debug.LogWarning("[BRTV] falta VRM " + vrmPath); return; }
        RuntimeGltfInstance plantilla;
        try { plantilla = await Cargar(vrmPath); }
        catch (Exception e) { Debug.LogError("[BRTV] no pude cargar " + vrmPath + ": " + e.Message); return; }
        if (this == null || pedido != vrmPath) return;      // llegó otro pedido mientras cargaba
        if (plantilla.gameObject.activeSelf)          // la primera vez: la plantilla queda escondida y se clona
        {
            plantilla.ShowMeshes(); plantilla.EnableUpdateWhenOffscreen();
            Aligerar(plantilla.gameObject);
            plantilla.gameObject.SetActive(false);
            plantilla.transform.SetParent(null);
            DontDestroyOnLoad(plantilla.gameObject);
        }
        modelo = Instantiate(plantilla.gameObject, transform, false);
        modelo.name = "VRM_" + id;
        modelo.transform.localPosition = Vector3.zero; modelo.transform.localRotation = Quaternion.identity;
        modelo.SetActive(true);
        anim = modelo.GetComponent<Animator>(); proxy = modelo.GetComponent<VRMBlendShapeProxy>();
        foreach (HumanBodyBones b in Enum.GetValues(typeof(HumanBodyBones)))
        {
            if (b == HumanBodyBones.LastBone) continue;
            var t = anim.GetBoneTransform(b); if (t != null) hueso[b] = t;
        }
        anim.enabled = false;   // los huesos los movemos a mano

        // escala: todas miden `altura`
        var cab = hueso.ContainsKey(HumanBodyBones.Head) ? hueso[HumanBodyBones.Head].position.y - transform.position.y : 1.4f;
        float alto = cab / 0.88f;
        if (alto > 0.5f) modelo.transform.localScale = Vector3.one * (altura / alto);
        caderaRest = hueso[HumanBodyBones.Hips].localPosition;
        caderaAlto = hueso[HumanBodyBones.Hips].position.y - transform.position.y;

        if (modo != Modo.EnVivo)        // el personal: sin física de pelo (barato) y con otro color
            foreach (var sb in modelo.GetComponentsInChildren<VRMSpringBone>(true)) sb.enabled = false;
        if (tintePelo.a > 0) Teñir(tintePelo);
        Integrar();
        foreach (var r in modelo.GetComponentsInChildren<Renderer>(true)) r.shadowCastingMode = modo == Modo.EnVivo ? UnityEngine.Rendering.ShadowCastingMode.On : UnityEngine.Rendering.ShadowCastingMode.Off;

        Lista = true;
        if (modo == Modo.EnVivo && !string.IsNullOrEmpty(wsUrl)) _ = Escuchar();
    }

    // 20-nov: que las dolls «vivan» en la luz del set (antes se veían quemadas, como pegadas encima): MToon toma el color de las luces,
    // menos luz indirecta propia, sombra violeta suave y un borde de neón rosa/cian como el del estudio.
    void Integrar()
    {
        bool vivo = modo == Modo.EnVivo;
        foreach (var r in modelo.GetComponentsInChildren<Renderer>(true))
        {
            var mats = r.materials;
            foreach (var m in mats)
            {
                if (m.shader == null || !m.shader.name.Contains("MToon")) continue;
                if (m.HasProperty("_LightColorAttenuation")) m.SetFloat("_LightColorAttenuation", 0f);
                if (m.HasProperty("_IndirectLightIntensity")) m.SetFloat("_IndirectLightIntensity", 0.2f);
                if (m.HasProperty("_Color")) { var c = m.GetColor("_Color"); m.SetColor("_Color", new Color(c.r * 0.86f, c.g * 0.84f, c.b * 0.9f, c.a)); }
                if (m.HasProperty("_ShadeColor")) { var c = m.GetColor("_Color"); m.SetColor("_ShadeColor", new Color(c.r * 0.52f, c.g * 0.42f, c.b * 0.62f, 1)); }
                if (m.HasProperty("_ShadeShift")) m.SetFloat("_ShadeShift", -0.05f);
                if (m.HasProperty("_ShadeToony")) m.SetFloat("_ShadeToony", 0.75f);
                if (vivo && m.HasProperty("_RimColor"))
                {
                    m.SetColor("_RimColor", semilla % 2 < 1 ? new Color(1f, 0.25f, 0.75f) * 0.55f : new Color(0.25f, 0.85f, 1f) * 0.5f);
                    if (m.HasProperty("_RimFresnelPower")) m.SetFloat("_RimFresnelPower", 4f);
                    if (m.HasProperty("_RimLift")) m.SetFloat("_RimLift", 0.05f);
                    if (m.HasProperty("_RimLightingMix")) m.SetFloat("_RimLightingMix", 0.6f);
                }
                if (m.HasProperty("_EmissionColor")) m.SetColor("_EmissionColor", m.GetColor("_EmissionColor") * 0.6f);
            }
            r.materials = mats;
        }
    }

    void Teñir(Color c)
    {
        foreach (var r in modelo.GetComponentsInChildren<Renderer>(true))
        {
            var mats = r.materials;   // copia por instancia
            foreach (var m in mats)
            {
                var n = m.name.ToLowerInvariant();
                if (!n.Contains("hair")) continue;
                if (m.HasProperty("_Color")) m.SetColor("_Color", c);
                if (m.HasProperty("_ShadeColor")) m.SetColor("_ShadeColor", c * 0.55f);
            }
            r.materials = mats;
        }
    }

    // ------------------------------------------------------------------ WebSocket del overlay (eco VMC)
    readonly object cerrojo = new object();
    Dictionary<string, object> cuadro; bool nuevo;
    CancellationTokenSource cts;

    async Task Escuchar()
    {
        cts = new CancellationTokenSource();
        var buf = new byte[1 << 16];
        while (!cts.IsCancellationRequested)
        {
            try
            {
                using (var ws = new ClientWebSocket())
                {
                    await ws.ConnectAsync(new Uri(wsUrl), cts.Token);
                    var sb = new StringBuilder();
                    while (ws.State == WebSocketState.Open && !cts.IsCancellationRequested)
                    {
                        var r = await ws.ReceiveAsync(new ArraySegment<byte>(buf), cts.Token);
                        if (r.MessageType == WebSocketMessageType.Close) break;
                        sb.Append(Encoding.UTF8.GetString(buf, 0, r.Count));
                        if (!r.EndOfMessage) continue;
                        var txt = sb.ToString(); sb.Clear();
                        if (txt.IndexOf("\"cuadro\"", StringComparison.Ordinal) < 0) continue;
                        if (MiniJson.Parse(txt) is Dictionary<string, object> m && m.TryGetValue("d", out var d) && d is Dictionary<string, object> dd)
                            lock (cerrojo) { cuadro = dd; nuevo = true; }
                    }
                }
            }
            catch (Exception) { }
            try { await Task.Delay(3000, cts.Token); } catch { }
        }
    }

    void OnDestroy() { cts?.Cancel(); }

    static readonly Dictionary<string, BlendShapePreset> PRESET = new Dictionary<string, BlendShapePreset>(StringComparer.OrdinalIgnoreCase)
    {
        {"a", BlendShapePreset.A}, {"i", BlendShapePreset.I}, {"u", BlendShapePreset.U}, {"e", BlendShapePreset.E}, {"o", BlendShapePreset.O},
        {"joy", BlendShapePreset.Joy}, {"sorrow", BlendShapePreset.Sorrow}, {"fun", BlendShapePreset.Fun}, {"angry", BlendShapePreset.Angry},
        {"blink", BlendShapePreset.Blink}, {"blink_l", BlendShapePreset.Blink_L}, {"blink_r", BlendShapePreset.Blink_R}, {"neutral", BlendShapePreset.Neutral},
    };

    static float F(object o) => o is double d ? (float)d : 0f;

    bool AplicarCuadro()
    {
        Dictionary<string, object> d;
        lock (cerrojo) { if (!nuevo) return false; d = cuadro; nuevo = false; }
        if (d.TryGetValue("h", out var ho) && ho is Dictionary<string, object> h)
            foreach (var kv in h)
            {
                if (!Enum.TryParse(kv.Key, out HumanBodyBones b) || !hueso.TryGetValue(b, out var t)) continue;
                if (!(kv.Value is List<object> q) || q.Count < 4) continue;
                var rot = new Quaternion(F(q[0]), F(q[1]), F(q[2]), F(q[3]));
                t.localRotation = Quaternion.Slerp(t.localRotation, rot, 0.6f);
            }
        if (!sentada && d.TryGetValue("c", out var co) && co is List<object> c && c.Count >= 3)
        {
            if (!c0.HasValue) c0 = new Vector3(F(c[0]), F(c[1]), F(c[2]));
            var dv = new Vector3(F(c[0]), F(c[1]), F(c[2])) - c0.Value;
            dv = Vector3.ClampMagnitude(dv, 0.35f);     // que no se salga del puesto
            hueso[HumanBodyBones.Hips].localPosition = caderaRest + dv;
        }
        if (proxy != null && d.TryGetValue("b", out var bo) && bo is Dictionary<string, object> bs)
        {
            foreach (var kv in bs)
            {
                var k = PRESET.TryGetValue(kv.Key, out var p) ? BlendShapeKey.CreateFromPreset(p) : BlendShapeKey.CreateUnknown(kv.Key);
                proxy.AccumulateValue(k, F(kv.Value));
            }
            proxy.Apply();
        }
        UltimoCuadro = Time.time;
        return true;
    }
    Vector3? c0;

    // ------------------------------------------------------------------ poses
    Quaternion Dir(Vector3 reposo, Vector3 deseada) => Quaternion.FromToRotation(reposo, deseada.normalized);

    void Rot(HumanBodyBones b, Quaternion q, float k)
    { if (hueso.TryGetValue(b, out var t)) t.localRotation = Quaternion.Slerp(t.localRotation, q, k); }

    // brazo apuntando a `codo` (dir. en espacio del modelo) y antebrazo a `mano`
    void Brazo(bool izq, Vector3 codo, Vector3 mano, float k)
    {
        var rest = izq ? Vector3.left : Vector3.right;
        var qU = Dir(rest, codo);
        Rot(izq ? HumanBodyBones.LeftUpperArm : HumanBodyBones.RightUpperArm, qU, k);
        Rot(izq ? HumanBodyBones.LeftLowerArm : HumanBodyBones.RightLowerArm, Dir(rest, Quaternion.Inverse(qU) * mano), k);
        Rot(izq ? HumanBodyBones.LeftShoulder : HumanBodyBones.RightShoulder, Quaternion.identity, k);
    }

    void Sentar(float k)
    {
        Rot(HumanBodyBones.LeftUpperLeg, Quaternion.Euler(-88, 0, -4), k);
        Rot(HumanBodyBones.RightUpperLeg, Quaternion.Euler(-88, 0, 4), k);
        Rot(HumanBodyBones.LeftLowerLeg, Quaternion.Euler(84, 0, 0), k);
        Rot(HumanBodyBones.RightLowerLeg, Quaternion.Euler(84, 0, 0), k);
        Rot(HumanBodyBones.LeftFoot, Quaternion.identity, k); Rot(HumanBodyBones.RightFoot, Quaternion.identity, k);
        // la cadera baja al asiento (en espacio del modelo escalado)
        var s = modelo.transform.localScale.y;
        var y = (asiento + 0.15f) / Mathf.Max(0.01f, s);
        var h = hueso[HumanBodyBones.Hips];
        var objetivo = new Vector3(caderaRest.x, caderaRest.y - (caderaAlto / s - y), caderaRest.z + 0.05f / s);
        h.localPosition = Vector3.Lerp(h.localPosition, objetivo, k);
    }

    void LateUpdate()
    {
        if (!Lista) return;
        float t = Time.time + semilla, dt = Time.deltaTime, k = Mathf.Min(1, dt * 6);

        if (modo == Modo.EnVivo)
        {
            bool vivo = AplicarCuadro() || Time.time - UltimoCuadro < 1.5f;
            if (!vivo)
            {   // sin stack VMC: reposo que respira
                Brazo(true, new Vector3(-0.35f, -1, 0.05f), new Vector3(-0.25f, -1, 0.25f), Mathf.Min(1, dt * 3));
                Brazo(false, new Vector3(0.35f, -1, 0.05f), new Vector3(0.25f, -1, 0.25f), Mathf.Min(1, dt * 3));
                Rot(HumanBodyBones.Spine, Quaternion.Euler(Mathf.Sin(t * 1.3f) * 1.2f, 0, 0), k);
                Rot(HumanBodyBones.Head, Quaternion.Euler(Mathf.Sin(t * 0.37f) * 4, Mathf.Sin(t * 0.23f) * 8, 0), Mathf.Min(1, dt * 2));
                if (!sentada) hueso[HumanBodyBones.Hips].localPosition = Vector3.Lerp(hueso[HumanBodyBones.Hips].localPosition, caderaRest, k);
                Parpadear(dt);
            }
            if (sentada) Sentar(1);
            return;
        }

        if (modo == Modo.Tecleando)
        {
            Sentar(1);
            Rot(HumanBodyBones.Spine, Quaternion.Euler(8, 0, 0), k);
            float tecla = Mathf.Sin(t * 13) * 0.025f, tecla2 = Mathf.Sin(t * 11.3f + 1) * 0.025f;
            bool pausa = Mathf.Sin(t * 0.21f) > 0.75f;          // a ratos se echa atrás y mira
            Brazo(true, new Vector3(-0.35f, -0.85f, 0.45f), new Vector3(0.15f, 0.05f + (pausa ? 0 : tecla), 1), k);
            Brazo(false, new Vector3(0.35f, -0.85f, 0.45f), new Vector3(-0.15f, 0.05f + (pausa ? 0 : tecla2), 1), k);
            float yaw = Mathf.Sin(t * 0.17f) * 18 + (pausa ? 25 * Mathf.Sign(Mathf.Sin(semilla)) : 0);
            Rot(HumanBodyBones.Neck, Quaternion.Euler(6, yaw * 0.4f, 0), k * 0.5f);
            Rot(HumanBodyBones.Head, Quaternion.Euler(8, yaw * 0.6f, 0), k * 0.5f);
        }
        else if (modo == Modo.Holomesa)
        {
            Rot(HumanBodyBones.Spine, Quaternion.Euler(12, Mathf.Sin(t * 0.3f) * 10, 0), k);
            float g = Mathf.Sin(t * 0.9f);
            Brazo(true, new Vector3(-0.3f, -0.7f, 0.5f), new Vector3(-0.1f, -0.2f + g * 0.25f, 1), k * 0.5f);
            Brazo(false, new Vector3(0.45f, -0.9f, 0.1f), new Vector3(0.3f, -1, 0.3f), k * 0.5f);
            Rot(HumanBodyBones.Head, Quaternion.Euler(22, Mathf.Sin(t * 0.4f) * 15, 0), k * 0.4f);
        }
        else if (modo == Modo.Camarografa)
        {
            Brazo(true, new Vector3(-0.25f, -0.6f, 0.75f), new Vector3(0.2f, 0.1f, 1), k);
            Brazo(false, new Vector3(0.25f, -0.6f, 0.75f), new Vector3(-0.2f, 0.1f, 1), k);
            Rot(HumanBodyBones.Head, Quaternion.Euler(10 + Mathf.Sin(t * 0.5f) * 3, Mathf.Sin(t * 0.2f) * 6, 0), k * 0.5f);
        }
        else // Parada: con una tablet, mira a su alrededor
        {
            Brazo(true, new Vector3(-0.3f, -0.9f, 0.3f), new Vector3(0.3f, -0.1f, 1), k);
            Brazo(false, new Vector3(0.35f, -1, 0.05f), new Vector3(0.25f, -1, 0.2f), k);
            Rot(HumanBodyBones.Head, Quaternion.Euler(18 + Mathf.Sin(t * 0.3f) * 10, Mathf.Sin(t * 0.25f) * 25, 0), k * 0.4f);
            Rot(HumanBodyBones.Spine, Quaternion.Euler(Mathf.Sin(t * 1.2f) * 1.5f, 0, 0), k);
        }
        Parpadear(dt);
    }

    void Parpadear(float dt)
    {
        if (proxy == null) return;
        parpado -= dt;
        proxy.ImmediatelySetValue(BlendShapeKey.CreateFromPreset(BlendShapePreset.Blink), parpado < 0 && parpado > -0.15f ? 1 : 0);
        if (parpado < -0.15f) parpado = 2.5f + UnityEngine.Random.value * 4;
    }
}
