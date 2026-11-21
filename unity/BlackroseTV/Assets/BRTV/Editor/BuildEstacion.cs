// BLACKROSE TV 2049 — la estación (pedido 2026-11-19). Escenografía para el canal autónomo: misma estética de la Mansión
// Bimbo (lacas negra/rosa, cromo, terciopelo blackrose, piso de mármol negro con cuadrícula neón, cielo synthwave) y los
// mismos shaders (BM_* copiados de ~/ALCOM/Projects/BimboMansion, ahora "BRTV/*").
// Sets en fila sobre el eje X, cada uno mirando a +Z (la cámara está en +Z):
//   estelar −82 · prensa −52 · deportes −26 · NOTICIARIO 0 (+ redacción y NÚCLEO detrás) · tiempo 26 · panel 50 · entrevistas/militar 76
// Menú: BlackRose TV > Construir estación / Compilar Linux. Batch: -executeMethod BuildEstacion.TodoBatch
using System.Collections.Generic;
using System.IO;
using System.Linq;
using TMPro;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.PostProcessing;

public static class BuildEstacion
{
    const string Raiz = "Assets/BRTV";
    const string MatDir = Raiz + "/Materials";
    const string MeshDir = Raiz + "/Meshes";
    const string EscenaPath = Raiz + "/Scenes/Estacion.unity";
    public const string BuildDir = "/home/alice/BlackroseTV_build";

    // ============================================================================================ menú / batch
    [MenuItem("BlackRose TV/Construir estación")] public static void Menu() { Construir(); }
    [MenuItem("BlackRose TV/Compilar Linux")] public static void MenuBuild() { Compilar(); }

    public static void TodoBatch()
    {
        try { Construir(); var r = Compilar(); EditorApplication.Exit(r ? 0 : 1); }
        catch (System.Exception e) { Debug.LogException(e); EditorApplication.Exit(1); }
    }
    public static void SoloEscenaBatch()
    {
        try { Construir(); EditorApplication.Exit(0); }
        catch (System.Exception e) { Debug.LogException(e); EditorApplication.Exit(1); }
    }

    // ============================================================================================ materiales
    static Color Hex(string h) { ColorUtility.TryParseHtmlString(h, out var c); return c; }
    static void Dir(string d) { if (!AssetDatabase.IsValidFolder(d)) { var p = Path.GetDirectoryName(d).Replace('\\', '/'); Dir(p); AssetDatabase.CreateFolder(p, Path.GetFileName(d)); } }
    static Material Load(string name, string shader)
    {
        Dir(MatDir); var path = MatDir + "/" + name + ".mat";
        var m = AssetDatabase.LoadAssetAtPath<Material>(path);
        var sh = Shader.Find(shader);
        if (m == null) { m = new Material(sh); AssetDatabase.CreateAsset(m, path); }
        else if (m.shader != sh) m.shader = sh;
        return m;
    }
    static Material Std(string name, string hex, float metal, float smooth, Color? emit = null)
    {
        var m = Load(name, "Standard");
        m.color = Hex(hex); m.SetFloat("_Metallic", metal); m.SetFloat("_Glossiness", smooth);
        if (emit.HasValue) { m.EnableKeyword("_EMISSION"); m.SetColor("_EmissionColor", emit.Value); m.globalIlluminationFlags = MaterialGlobalIlluminationFlags.None; }
        else { m.DisableKeyword("_EMISSION"); m.SetColor("_EmissionColor", Color.black); }
        m.enableInstancing = true; EditorUtility.SetDirty(m); return m;
    }
    static Material Neon(string name, Color c, float k) => Std(name, "#050308", 0, 0.6f, c * k);
    static Material Transp(string name, Color c, float smooth, Color? emit = null)
    {
        var m = Std(name, "#ffffff", 0.2f, smooth, emit); m.color = c;
        m.SetFloat("_Mode", 3); m.SetOverrideTag("RenderType", "Transparent");
        m.SetInt("_SrcBlend", (int)BlendMode.One); m.SetInt("_DstBlend", (int)BlendMode.OneMinusSrcAlpha); m.SetInt("_ZWrite", 0);
        m.DisableKeyword("_ALPHATEST_ON"); m.DisableKeyword("_ALPHABLEND_ON"); m.EnableKeyword("_ALPHAPREMULTIPLY_ON");
        m.renderQueue = 3000; EditorUtility.SetDirty(m); return m;
    }
    static Material Aditivo(string name, Color tint)
    {
        var m = Load(name, "Legacy Shaders/Particles/Additive");
        var def = AssetDatabase.GetBuiltinExtraResource<Material>("Default-Particle.mat");
        m.SetColor("_TintColor", tint); EditorUtility.SetDirty(m); return m;
    }
    static Material AditivoPlano(string name, Color tint)
    {   // sin textura de partícula (blanco pleno) para hologramas sólidos
        var m = Load(name, "Legacy Shaders/Particles/Additive");
        m.mainTexture = Texture2D.whiteTexture; m.SetColor("_TintColor", tint); EditorUtility.SetDirty(m); return m;
    }
    static Material TV(string name, int mode, float aspect, float seed, float bright = 1.9f)
    {
        var m = Load(name, "BRTV/TVScreen");
        m.SetFloat("_Mode", mode); m.SetFloat("_Aspect", aspect); m.SetFloat("_Seed", seed); m.SetFloat("_Bright", bright); EditorUtility.SetDirty(m); return m;
    }
    static Material Beam(string name, Color c, float inten, float kind = 0)
    {
        var m = Load(name, "BRTV/LightBeam"); m.SetColor("_Color", c); m.SetFloat("_Intensity", inten); m.SetFloat("_Kind", kind); EditorUtility.SetDirty(m); return m;
    }
    static Material Grid(string name, string baseHex, float gloss, Color grid, Color major, float cell, float majorN, float line, float inten, float wall, float ceil, bool vetas)
    {
        var g = Load(name, "BRTV/NeonGrid");
        g.SetColor("_Color", Hex(baseHex)); g.SetFloat("_Glossiness", gloss); g.SetFloat("_Metallic", 0.1f);
        g.SetColor("_GridColor", grid); g.SetColor("_MajorColor", major);
        g.SetFloat("_Cell", cell); g.SetFloat("_CellY", cell); g.SetFloat("_Major", majorN);
        g.SetFloat("_Line", line); g.SetFloat("_Intensity", inten); g.SetFloat("_WallFactor", wall); g.SetFloat("_CeilFactor", ceil);
        if (vetas)
        {
            var vt = AssetDatabase.LoadAssetAtPath<Texture2D>(Raiz + "/Textures/PolyHaven/marble_01_albedo.jpg");
            g.SetTexture("_VeinTex", vt); g.SetColor("_VeinColor", new Color(0.33f, 0.2f, 0.42f, 1)); g.SetFloat("_VeinScale", 3f); g.SetFloat("_VeinSharp", 3f);
        }
        else g.SetColor("_VeinColor", new Color(0, 0, 0, 0));
        EditorUtility.SetDirty(g); return g;
    }

    static readonly Color PINK = new Color(1f, 0.18f, 0.65f), CYAN = new Color(0.2f, 0.95f, 1f), VIOL = new Color(0.55f, 0.2f, 1f),
                          GOLD = new Color(1f, 0.75f, 0.25f), WHITE = new Color(1f, 0.95f, 0.98f), RED = new Color(1f, 0.12f, 0.15f), GREEN = new Color(0.25f, 1f, 0.6f);

    static Material mPiso, mPisoSet, mPared, mParedGrid, mTecho, mNegro, mRosa, mPerla, mCromo, mLavanda, mVelvet, mCian, mOro, mVidrio, mHolo, mHoloRosa,
                    nRosa, nCian, nViol, nOro, nBlanco, nRojo, nVerde, mFoco, mPantNegra, mCuero, mMantel, mCiudad, mCiudadGlow;
    static Material tvIdent, tvHud, tvHud2, tvTiempo, tvCancha, tvTactico, tvSynth, tvEQ, tvBimbo, tvIdentMedio;

    static void Materiales()
    {
        mPiso = Grid("Piso_MarmolGrid", "#05030A", 0.93f, PINK * 0.9f, CYAN, 1f, 4f, 0.018f, 0.55f, 0.5f, 0.2f, true);
        mPisoSet = Grid("Piso_Set", "#07040D", 0.96f, VIOL, PINK, 0.5f, 4f, 0.012f, 0.9f, 0.5f, 0.2f, true);
        mParedGrid = Grid("Pared_Grid", "#0B0816", 0.6f, VIOL * 0.7f, PINK * 0.6f, 1.2f, 0, 0.012f, 0.35f, 1f, 0.2f, false);
        mTecho = Grid("Techo", "#030205", 0.3f, VIOL * 0.4f, CYAN * 0.4f, 2f, 0, 0.02f, 0.4f, 1f, 1f, false);
        mPared = Std("Pared_Perla", "#22243C", 0.1f, 0.55f);
        mNegro = Std("Laca_Negra", "#0C0A0D", 0f, 0.93f);
        mRosa = Std("Laca_Rosa", "#FF4FB8", 0f, 0.85f);
        mPerla = Std("Laca_Perla", "#EFE6EE", 0.15f, 0.9f);
        mCromo = Std("Cromo", "#E8E8F0", 1f, 0.95f);
        mLavanda = Std("Satin_Lavanda", "#A24BFF", 0f, 0.7f);
        mVelvet = Std("Terciopelo_Blackrose", "#7A1033", 0f, 0.38f);
        mCian = Std("Satin_Cian", "#2FD8F0", 0f, 0.75f);
        mOro = Std("Oro", "#FFC861", 1f, 0.85f);
        mCuero = Std("Cuero_Negro", "#141016", 0f, 0.6f);
        mMantel = Std("Mantel_Negro", "#0E0B12", 0f, 0.3f);
        mPantNegra = Std("Pantalla_Apagada", "#020203", 0.2f, 0.98f);
        mVidrio = Transp("Vidrio", new Color(0.12f, 0.06f, 0.2f, 0.18f), 0.98f);
        mHolo = AditivoPlano("Holo_Cian", new Color(0.2f, 0.85f, 1f, 0.35f));
        mHoloRosa = AditivoPlano("Holo_Rosa", new Color(1f, 0.25f, 0.7f, 0.35f));
        nRosa = Neon("Neon_Rosa", PINK, 4f); nCian = Neon("Neon_Cian", CYAN, 4f); nViol = Neon("Neon_Violeta", VIOL, 4f);
        nOro = Neon("Neon_Oro", GOLD, 3.5f); nBlanco = Neon("Neon_Blanco", WHITE, 3f); nRojo = Neon("Neon_Rojo", RED, 5f); nVerde = Neon("Neon_Verde", GREEN, 3f);
        mFoco = Neon("Foco_Bombilla", new Color(1f, 0.85f, 0.6f), 3.2f);
        tvIdent = TV("TV_Ident", 8, 1.78f, 0.1f); tvIdentMedio = TV("TV_Ident_Medio", 8, 1.78f, 0.7f);
        tvHud = TV("TV_HUD", 1, 1.6f, 0.3f); tvHud2 = TV("TV_HUD_b", 1, 1.0f, 2.3f, 1.6f);
        tvTiempo = TV("TV_Tiempo", 5, 2.4f, 0.5f); tvCancha = TV("TV_Cancha", 6, 2.2f, 0.2f);
        tvTactico = TV("TV_Tactico", 7, 1.67f, 0.4f, 1.6f); tvSynth = TV("TV_Synth", 0, 2.8f, 0.9f); tvEQ = TV("TV_EQ", 3, 0.5f, 1.1f);
        tvBimbo = TV("TV_BimboTV", 4, 1.78f, 0.6f);
        mCiudad = Std("Ciudad_Ventanas", "#08060E", 0.2f, 0.7f); mCiudad.SetTexture("_MainTex", null);
        var vt = TexVentanas(); mCiudad.EnableKeyword("_EMISSION"); mCiudad.SetTexture("_EmissionMap", vt); mCiudad.SetColor("_EmissionColor", new Color(1f, 0.75f, 1.1f) * 1.6f);
        mCiudad.globalIlluminationFlags = MaterialGlobalIlluminationFlags.None; EditorUtility.SetDirty(mCiudad);
        mCiudadGlow = Neon("Ciudad_Antena", PINK, 6f);
        AssetDatabase.SaveAssets();
    }

    static Texture2D TexVentanas()
    {
        var path = Raiz + "/Textures/ventanas.png";
        if (!File.Exists(path))
        {
            int n = 256; var t = new Texture2D(n, n); var r = new System.Random(7);
            for (int y = 0; y < n; y++) for (int x = 0; x < n; x++)
                {
                    int cx = x / 8, cy = y / 8; bool marco = (x % 8) < 2 || (y % 8) < 3;
                    double h = (cx * 73856093 ^ cy * 19349663) % 1000 / 1000.0;
                    Color c = Color.black;
                    if (!marco && h > 0.55) c = h > 0.93 ? new Color(1f, 0.3f, 0.75f) : h > 0.86 ? new Color(0.3f, 0.9f, 1f) : new Color(0.55f, 0.45f, 0.7f) * (float)(0.4 + r.NextDouble() * 0.4);
                    t.SetPixel(x, y, c);
                }
            File.WriteAllBytes(path, t.EncodeToPNG()); AssetDatabase.ImportAsset(path);
        }
        return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
    }

    // ============================================================================================ mallas
    static Mesh conoMesh, toroMesh, toroFino, cajaUV;
    static Mesh Guardar(Mesh m, string n) { Dir(MeshDir); var p = MeshDir + "/" + n + ".asset"; AssetDatabase.DeleteAsset(p); AssetDatabase.CreateAsset(m, p); return m; }
    static Mesh Cono(int seg = 24)
    {   // punta en el origen, base a 1 m en −Y (radio 1); uv.y 0 en la punta (el foco) → 1 lejos
        var v = new List<Vector3>(); var uv = new List<Vector2>(); var tr = new List<int>();
        for (int i = 0; i <= seg; i++)
        {
            float a = i / (float)seg * Mathf.PI * 2;
            v.Add(new Vector3(Mathf.Cos(a) * 0.02f, 0, Mathf.Sin(a) * 0.02f)); uv.Add(new Vector2(i / (float)seg, 0));
            v.Add(new Vector3(Mathf.Cos(a), -1, Mathf.Sin(a))); uv.Add(new Vector2(i / (float)seg, 1));
        }
        for (int i = 0; i < seg; i++) { int a = i * 2; tr.AddRange(new[] { a, a + 2, a + 1, a + 1, a + 2, a + 3 }); }
        var m = new Mesh { name = "Cono" }; m.SetVertices(v); m.SetUVs(0, uv); m.SetTriangles(tr, 0); m.RecalculateNormals(); m.RecalculateBounds();
        return Guardar(m, "Cono");
    }
    static Mesh Toro(string n, float R, float r, int seg = 64, int lados = 10)
    {   // anillo acostado (plano XZ), radio mayor R
        var v = new List<Vector3>(); var no = new List<Vector3>(); var uv = new List<Vector2>(); var tr = new List<int>();
        for (int i = 0; i <= seg; i++)
        {
            float a = i / (float)seg * Mathf.PI * 2; var c = new Vector3(Mathf.Cos(a), 0, Mathf.Sin(a));
            for (int j = 0; j <= lados; j++)
            {
                float b = j / (float)lados * Mathf.PI * 2; var d = c * Mathf.Cos(b) + Vector3.up * Mathf.Sin(b);
                v.Add(c * R + d * r); no.Add(d); uv.Add(new Vector2(i / (float)seg, j / (float)lados));
            }
        }
        int L = lados + 1;
        for (int i = 0; i < seg; i++) for (int j = 0; j < lados; j++) { int a = i * L + j; tr.AddRange(new[] { a, a + 1, a + L, a + 1, a + L + 1, a + L }); }
        var m = new Mesh { name = n }; m.SetVertices(v); m.SetNormals(no); m.SetUVs(0, uv); m.SetTriangles(tr, 0); m.RecalculateBounds();
        return Guardar(m, n);
    }

    // ============================================================================================ primitivas
    static GameObject Prim(PrimitiveType t, Transform p, string name, Vector3 lp, Vector3 size, Material m, Vector3? euler = null)
    {
        var g = GameObject.CreatePrimitive(t); g.name = name; g.transform.SetParent(p, false);
        g.transform.localPosition = lp; g.transform.localScale = size; if (euler.HasValue) g.transform.localEulerAngles = euler.Value;
        g.GetComponent<Renderer>().sharedMaterial = m; Object.DestroyImmediate(g.GetComponent<Collider>());
        return g;
    }
    static GameObject Box(Transform p, string n, Vector3 lp, Vector3 s, Material m, Vector3? e = null) => Prim(PrimitiveType.Cube, p, n, lp, s, m, e);
    static GameObject Cyl(Transform p, string n, Vector3 lp, Vector3 s, Material m, Vector3? e = null) => Prim(PrimitiveType.Cylinder, p, n, lp, s, m, e);
    static GameObject Esf(Transform p, string n, Vector3 lp, float d, Material m) => Prim(PrimitiveType.Sphere, p, n, lp, Vector3.one * d, m);
    static GameObject Quad(Transform p, string n, Vector3 lp, Vector2 s, Material m, Vector3? e = null)
    {
        var g = Prim(PrimitiveType.Quad, p, n, lp, new Vector3(s.x, s.y, 1), m, e ?? new Vector3(0, 180, 0));   // mira a +Z
        g.GetComponent<Renderer>().shadowCastingMode = ShadowCastingMode.Off; return g;
    }
    static GameObject MeshGO(Transform p, string n, Mesh mesh, Vector3 lp, Vector3 s, Material m, Vector3? e = null)
    {
        var g = new GameObject(n); g.transform.SetParent(p, false); g.transform.localPosition = lp; g.transform.localScale = s;
        if (e.HasValue) g.transform.localEulerAngles = e.Value;
        g.AddComponent<MeshFilter>().sharedMesh = mesh; var r = g.AddComponent<MeshRenderer>(); r.sharedMaterial = m; return g;
    }
    static GameObject Vacio(Transform p, string n, Vector3 lp, Vector3? e = null)
    {
        var g = new GameObject(n); g.transform.SetParent(p, false); g.transform.localPosition = lp; if (e.HasValue) g.transform.localEulerAngles = e.Value; return g;
    }
    static TextMeshPro Texto(Transform p, string name, Vector3 lp, string text, float size, Color c, float ancho = 20, Vector3? euler = null, bool negrita = true)
    {
        var g = new GameObject(name); g.transform.SetParent(p, false); g.transform.localPosition = lp; g.transform.localEulerAngles = euler ?? new Vector3(0, 180, 0);
        var t = g.AddComponent<TextMeshPro>(); t.text = text; t.fontSize = size; t.alignment = TextAlignmentOptions.Center; t.color = c;
        t.enableWordWrapping = false; t.rectTransform.sizeDelta = new Vector2(ancho, size * 0.2f + 0.5f);
        if (negrita) t.fontStyle = FontStyles.Bold;
        t.GetComponent<MeshRenderer>().shadowCastingMode = ShadowCastingMode.Off;
        return t;
    }
    static Light Luz(Transform p, string n, LightType tipo, Vector3 lp, Vector3 mirar, Color c, float inten, float rango, float ang = 40, bool sombra = false)
    {
        var g = Vacio(p, n, lp); var l = g.AddComponent<Light>(); l.type = tipo; l.color = c; l.intensity = inten; l.range = rango; l.spotAngle = ang;
        l.shadows = sombra ? LightShadows.Soft : LightShadows.None; l.renderMode = LightRenderMode.ForcePixel;
        if (tipo == LightType.Spot) g.transform.LookAt(p.TransformPoint(mirar));
        return l;
    }
    // foco de techo con haz visible (cono aditivo) apuntando a `objetivo` (coordenadas locales del set)
    static void Foco(Transform p, string n, Vector3 lp, Vector3 objetivo, Color c, float inten, bool haz = true, bool sombra = false, float ang = 34)
    {
        if (n.StartsWith("Llave")) inten *= 0.6f;      // 20-nov: las llaves quemaban a las dolls (MToon); el set sube por ambiente
        else inten *= 1.25f;
        var l = Luz(p, n, LightType.Spot, lp, objetivo, c, inten, Vector3.Distance(lp, objetivo) * 2.2f, ang, sombra);
        var cuerpo = Cyl(l.transform, "Carcasa", Vector3.zero, new Vector3(0.28f, 0.18f, 0.28f), mNegro, new Vector3(90, 0, 0));
        Cyl(l.transform, "Lente", new Vector3(0, 0, 0.17f), new Vector3(0.22f, 0.01f, 0.22f), Neon("Lente_" + ColorUtility.ToHtmlStringRGB(c), c, 3f), new Vector3(90, 0, 0));
        if (haz)
        {
            float largo = Mathf.Min(Vector3.Distance(lp, objetivo) * 0.9f, 7f), rad = Mathf.Tan(ang * 0.5f * Mathf.Deg2Rad) * largo * 0.8f;
            var cono = MeshGO(l.transform, "Haz", conoMesh, new Vector3(0, 0, 0.18f), new Vector3(rad, largo, rad), Beam("Haz_" + ColorUtility.ToHtmlStringRGB(c), c, 0.35f), new Vector3(-90, 0, 0));
            cono.GetComponent<Renderer>().shadowCastingMode = ShadowCastingMode.Off;
        }
    }

    // monitor de escritorio con pantalla viva
    static void Monitor(Transform p, string n, Vector3 lp, float yaw, float ancho, Material pant)
    {
        var g = Vacio(p, n, lp, new Vector3(0, yaw, 0));
        Box(g.transform, "Marco", new Vector3(0, ancho * 0.31f, 0), new Vector3(ancho, ancho * 0.6f, 0.03f), mNegro);
        Quad(g.transform, "Pantalla", new Vector3(0, ancho * 0.31f, 0.017f), new Vector2(ancho * 0.94f, ancho * 0.54f), pant);
        Box(g.transform, "Pie", new Vector3(0, 0.02f, -0.05f), new Vector3(0.18f, 0.02f, 0.14f), mCromo);
        Box(g.transform, "Cuello", new Vector3(0, ancho * 0.12f, -0.03f), new Vector3(0.03f, ancho * 0.24f, 0.03f), mCromo);
    }

    // silla giratoria (asiento a `alto`), mira a +Z
    static void Silla(Transform p, string n, Vector3 lp, float yaw, Material tapiz, float alto = 0.5f, bool respaldoAlto = false)
    {
        var g = Vacio(p, n, lp, new Vector3(0, yaw, 0));
        Cyl(g.transform, "Base", new Vector3(0, 0.03f, 0), new Vector3(0.6f, 0.03f, 0.6f), mCromo);
        Cyl(g.transform, "Columna", new Vector3(0, alto * 0.5f, 0), new Vector3(0.06f, alto * 0.5f, 0.06f), mCromo);
        Box(g.transform, "Asiento", new Vector3(0, alto, 0), new Vector3(0.5f, 0.09f, 0.5f), tapiz);
        float rh = respaldoAlto ? 0.62f : 0.45f;
        Box(g.transform, "Respaldo", new Vector3(0, alto + rh * 0.5f, -0.26f), new Vector3(0.48f, rh, 0.08f), tapiz, new Vector3(-8, 0, 0));
        Box(g.transform, "RespaldoNeon", new Vector3(0, alto + rh * 0.5f, -0.305f), new Vector3(0.06f, rh * 0.85f, 0.01f), nRosa, new Vector3(-8, 0, 0));
    }

    static void Sillon(Transform p, string n, Vector3 lp, float yaw, Material tapiz)
    {
        var g = Vacio(p, n, lp, new Vector3(0, yaw, 0));
        Box(g.transform, "Base", new Vector3(0, 0.22f, 0), new Vector3(0.9f, 0.44f, 0.8f), tapiz);
        Box(g.transform, "Respaldo", new Vector3(0, 0.7f, -0.33f), new Vector3(0.9f, 0.6f, 0.16f), tapiz, new Vector3(-10, 0, 0));
        Box(g.transform, "BrazoI", new Vector3(-0.42f, 0.55f, 0), new Vector3(0.12f, 0.3f, 0.8f), tapiz);
        Box(g.transform, "BrazoD", new Vector3(0.42f, 0.55f, 0), new Vector3(0.12f, 0.3f, 0.8f), tapiz);
        Box(g.transform, "Zocalo", new Vector3(0, 0.02f, 0), new Vector3(0.92f, 0.04f, 0.82f), nRosa);
    }

    // cámara de estudio (pedestal) — atrezo; si `opera`, una persona del canal la maneja
    static void CamaraEstudio(Transform p, string n, Vector3 lp, Vector3 mirar, bool opera)
    {
        var g = Vacio(p, n, lp); var dir = mirar - lp; dir.y = 0; g.transform.localRotation = Quaternion.LookRotation(dir);
        Cyl(g.transform, "Base", new Vector3(0, 0.08f, 0), new Vector3(0.9f, 0.08f, 0.9f), mNegro);
        Cyl(g.transform, "Columna", new Vector3(0, 0.7f, 0), new Vector3(0.14f, 0.6f, 0.14f), mCromo);
        var cuerpo = Box(g.transform, "Cuerpo", new Vector3(0, 1.42f, 0.05f), new Vector3(0.32f, 0.36f, 0.6f), mNegro);
        Cyl(g.transform, "Lente", new Vector3(0, 1.42f, 0.5f), new Vector3(0.22f, 0.22f, 0.22f), mNegro, new Vector3(90, 0, 0));
        Cyl(g.transform, "Cristal", new Vector3(0, 1.42f, 0.62f), new Vector3(0.18f, 0.01f, 0.18f), nViol, new Vector3(90, 0, 0));
        Box(g.transform, "Visor", new Vector3(0, 1.66f, -0.18f), new Vector3(0.3f, 0.2f, 0.04f), mNegro, new Vector3(-12, 0, 0));
        Quad(g.transform, "VisorPant", new Vector3(0, 1.66f, -0.205f), new Vector2(0.27f, 0.17f), tvIdent, new Vector3(-12, 0, 0));
        Box(g.transform, "Tally", new Vector3(0, 1.64f, 0.3f), new Vector3(0.08f, 0.04f, 0.04f), nRojo);
        Box(g.transform, "Logo", new Vector3(0.165f, 1.42f, 0.05f), new Vector3(0.01f, 0.06f, 0.4f), nRosa);
        if (opera) Persona(g.transform, "Camarografa", new Vector3(0, 0, -0.75f), 0, BRTVDoll.Modo.Camarografa, 1.62f);
    }

    static int personas;
    static readonly Color[] PELOS = { Hex("#FF5EC4"), Hex("#F4E9FF"), Hex("#4BE3FF"), Hex("#B38CFF"), Hex("#FF4057"), Hex("#2B2233"), Hex("#6FA8FF"), Hex("#7DFFC4"), Hex("#FFD27A") };
    static BRTVDoll Persona(Transform p, string n, Vector3 lp, float yaw, BRTVDoll.Modo modo, float altura = 1.66f, float asiento = 0.5f)
    {
        var g = Vacio(p, n, lp, new Vector3(0, yaw, 0));
        var d = g.AddComponent<BRTVDoll>(); d.modo = modo; d.altura = altura; d.asiento = asiento; d.sentada = modo == BRTVDoll.Modo.Tecleando;
        d.tintePelo = PELOS[personas++ % PELOS.Length]; d.semilla = personas * 7.3f; d.id = "personal" + personas;
        return d;
    }

    // puesto de trabajo de la redacción: escritorio + 2 monitores + silla + persona tecleando
    static void Puesto(Transform p, string n, Vector3 lp, float yaw, int i, bool persona)
    {
        var g = Vacio(p, n, lp, new Vector3(0, yaw, 0));
        Box(g.transform, "Cubierta", new Vector3(0, 0.74f, 0.45f), new Vector3(1.5f, 0.05f, 0.75f), mPerla);
        Box(g.transform, "Canto", new Vector3(0, 0.71f, 0.83f), new Vector3(1.5f, 0.02f, 0.01f), i % 2 == 0 ? nRosa : nCian);
        Box(g.transform, "Pata", new Vector3(0, 0.36f, 0.75f), new Vector3(1.4f, 0.72f, 0.06f), mNegro);
        Box(g.transform, "Teclado", new Vector3(0, 0.775f, 0.32f), new Vector3(0.45f, 0.015f, 0.14f), mNegro);
        Box(g.transform, "TeclasLuz", new Vector3(0, 0.784f, 0.32f), new Vector3(0.42f, 0.002f, 0.11f), i % 2 == 0 ? nViol : nCian);
        Monitor(g.transform, "MonitorA", new Vector3(-0.3f, 0.765f, 0.7f), 180 + 12, 0.62f, i % 3 == 0 ? tvHud : tvHud2);
        Monitor(g.transform, "MonitorB", new Vector3(0.32f, 0.765f, 0.7f), 180 - 12, 0.62f, i % 3 == 1 ? tvTactico : (i % 3 == 2 ? tvTiempo : tvHud));
        Box(g.transform, "Taza", new Vector3(0.6f, 0.82f, 0.4f), new Vector3(0.07f, 0.1f, 0.07f), mRosa);
        Silla(g.transform, "Silla", new Vector3(0, 0, -0.15f), 0, mNegro);
        if (persona) Persona(g.transform, "Periodista", new Vector3(0, 0, -0.1f), 0, BRTVDoll.Modo.Tecleando, 1.64f, 0.5f);
    }

    // ============================================================================================ salas
    static GameObject Sala(Transform raiz, string n, float x, float ancho, float fondo = 7f, float frente = 14f, float alto = 7.5f, bool paredFondo = true)
    {
        var s = Vacio(raiz, n, new Vector3(x, 0, 0));
        Box(s.transform, "Piso", new Vector3(0, -0.05f, (frente - fondo) * 0.5f), new Vector3(ancho, 0.1f, frente + fondo), mPiso);
        Box(s.transform, "Techo", new Vector3(0, alto, (frente - fondo) * 0.5f), new Vector3(ancho, 0.1f, frente + fondo), mTecho);
        if (paredFondo) Box(s.transform, "ParedFondo", new Vector3(0, alto * 0.5f, -fondo), new Vector3(ancho, alto, 0.2f), mParedGrid);
        Box(s.transform, "ParedIzq", new Vector3(-ancho * 0.5f, alto * 0.5f, (frente - fondo) * 0.5f), new Vector3(0.2f, alto, frente + fondo), mParedGrid);
        Box(s.transform, "ParedDer", new Vector3(ancho * 0.5f, alto * 0.5f, (frente - fondo) * 0.5f), new Vector3(0.2f, alto, frente + fondo), mParedGrid);
        Box(s.transform, "ParedFrente", new Vector3(0, alto * 0.5f, frente), new Vector3(ancho, alto, 0.2f), mParedGrid);
        // canaletas de luz en el techo y zócalo neón en las paredes
        for (float z = -fondo + 2; z < frente; z += 4) Box(s.transform, "LuzTecho", new Vector3(0, alto - 0.08f, z), new Vector3(ancho * 0.8f, 0.03f, 0.08f), nViol);
        Box(s.transform, "ZocaloI", new Vector3(-ancho * 0.5f + 0.11f, 0.06f, (frente - fondo) * 0.5f), new Vector3(0.02f, 0.04f, frente + fondo), nRosa);
        Box(s.transform, "ZocaloD", new Vector3(ancho * 0.5f - 0.11f, 0.06f, (frente - fondo) * 0.5f), new Vector3(0.02f, 0.04f, frente + fondo), nRosa);
        // parrilla de luces (truss) bajo el techo
        for (float xx = -ancho * 0.5f + 2; xx <= ancho * 0.5f - 2; xx += 4) Box(s.transform, "Truss", new Vector3(xx, alto - 0.9f, 1), new Vector3(0.12f, 0.12f, frente + fondo - 4), mCromo);
        Box(s.transform, "TrussX", new Vector3(0, alto - 0.9f, -1), new Vector3(ancho - 2, 0.12f, 0.12f), mCromo);
        Box(s.transform, "TrussX2", new Vector3(0, alto - 0.9f, 5), new Vector3(ancho - 2, 0.12f, 0.12f), mCromo);
        var probe = Vacio(s.transform, "Reflejos", new Vector3(0, 2.2f, 1)).AddComponent<ReflectionProbe>();
        probe.mode = ReflectionProbeMode.Realtime; probe.refreshMode = ReflectionProbeRefreshMode.OnAwake; probe.timeSlicingMode = ReflectionProbeTimeSlicingMode.IndividualFaces;
        probe.size = new Vector3(ancho, alto, frente + fondo); probe.center = new Vector3(0, alto * 0.5f - 2.2f, (frente - fondo) * 0.5f - 1); probe.resolution = 128; probe.boxProjection = true;
        probe.hdr = true;
        return s;
    }

    static BRTVSet Set(GameObject sala, string nombre, string titulo, bool sentadas, float asiento, Vector3 joy, float yawJoy, Vector3 kur, float yawKur)
    {
        var g = Vacio(sala.transform, "SET_" + nombre, Vector3.zero);
        var s = g.AddComponent<BRTVSet>(); s.nombre = nombre; s.titulo = titulo; s.sentadas = sentadas; s.asiento = asiento;
        s.puestoJoy = Vacio(g.transform, "Puesto_joy", joy, new Vector3(0, yawJoy, 0)).transform;
        s.puestoKuroki = Vacio(g.transform, "Puesto_kuroki", kur, new Vector3(0, yawKur, 0)).transform;
        s.planos = new BRTVPlano[0];
        return s;
    }
    static void Plano(BRTVSet s, string n, Vector3 pos, Vector3 mirar, float fov, string foco = "", float deriva = 0.25f)
    {
        var g = Vacio(s.transform, n, pos); g.transform.LookAt(s.transform.TransformPoint(mirar));
        var p = g.AddComponent<BRTVPlano>(); p.fov = fov; p.foco = foco; p.deriva = deriva;
        s.planos = s.planos.Concat(new[] { p }).ToArray();
    }
    // tarima circular con aro de neón
    static void Tarima(Transform p, Vector3 lp, float r, float h, Material aro)
    {
        Cyl(p, "TarimaAro", lp + Vector3.up * (h * 0.5f - 0.02f), new Vector3(r * 2 + 0.12f, h * 0.5f - 0.02f, r * 2 + 0.12f), aro);
        Cyl(p, "Tarima", lp + Vector3.up * (h * 0.5f), new Vector3(r * 2, h * 0.5f, r * 2), mNegro);
        Cyl(p, "TarimaPiso", lp + Vector3.up * (h + 0.001f), new Vector3(r * 2 - 0.2f, 0.001f, r * 2 - 0.2f), mPisoSet);
    }
    // escritorio curvo: segmentos sobre un arco de centro `c`, radio R, de a0 a a1 grados (0 = +Z)
    static void EscritorioArco(Transform p, string n, Vector3 c, float R, float a0, float a1, float alto, Material cuerpo, Material neon, int seg = 14)
    {
        var g = Vacio(p, n, Vector3.zero);
        float paso = (a1 - a0) / seg, largo = R * paso * Mathf.Deg2Rad * 1.04f;
        for (int i = 0; i < seg; i++)
        {
            float a = a0 + paso * (i + 0.5f); var dir = Quaternion.Euler(0, a, 0) * Vector3.forward;
            var pos = c + dir * R; var e = new Vector3(0, a, 0);
            Box(g.transform, "Cuerpo" + i, pos + Vector3.up * alto * 0.5f, new Vector3(largo, alto, 0.12f), cuerpo, e);
            Box(g.transform, "Cubierta" + i, pos + Vector3.up * alto - dir * 0.3f, new Vector3(largo * 1.02f, 0.05f, 0.75f), mCromo, e);
            Box(g.transform, "Vidrio" + i, pos + Vector3.up * (alto + 0.03f) - dir * 0.3f, new Vector3(largo * 1.02f, 0.012f, 0.72f), mNegro, e);
            Box(g.transform, "Neon" + i, pos + Vector3.up * 0.06f + dir * 0.065f, new Vector3(largo * 1.01f, 0.03f, 0.01f), neon, e);
            Box(g.transform, "NeonAlto" + i, pos + Vector3.up * (alto - 0.08f) + dir * 0.065f, new Vector3(largo * 1.01f, 0.012f, 0.01f), neon, e);
        }
    }

    // ============================================================================================ construir
    public static void Construir()
    {
        personas = 0;
        Dir(Raiz + "/Scenes");
        conoMesh = Cono(); toroMesh = Toro("Toro", 1f, 0.03f); toroFino = Toro("ToroFino", 1f, 0.012f, 96, 6);
        Materiales();
        var escena = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

        // ------------------------------------------------ ambiente: cielo synthwave de la mansión
        var cielo = Load("Cielo_Synth2049", "BRTV/SynthSky");
        cielo.SetVector("_SunDir", Quaternion.Euler(-6, 180, 0) * Vector3.forward);
        RenderSettings.skybox = cielo;
        RenderSettings.ambientMode = AmbientMode.Trilight;
        RenderSettings.ambientSkyColor = Hex("#6A4C98"); RenderSettings.ambientEquatorColor = Hex("#4A3470"); RenderSettings.ambientGroundColor = Hex("#20142E");   // 20-nov: el set estaba muy oscuro
        RenderSettings.ambientIntensity = 1.25f;
        RenderSettings.defaultReflectionMode = DefaultReflectionMode.Skybox;
        RenderSettings.fog = true; RenderSettings.fogMode = FogMode.ExponentialSquared; RenderSettings.fogDensity = 0.0035f; RenderSettings.fogColor = Hex("#1A0B24");

        var raiz = new GameObject("BLACKROSE_TV_2049").transform;

        Noticiario(raiz);
        Tiempo(raiz, 26);
        Deportes(raiz, -26);
        Panel(raiz, 50);
        EntrevistasMilitar(raiz, 76);
        Prensa(raiz, -52);
        Estelar(raiz, -82);
        Ciudad(raiz);

        // ------------------------------------------------ conductoras
        var joy = Vacio(raiz, "Joy", Vector3.zero).AddComponent<BRTVDoll>(); joy.id = "joy"; joy.modo = BRTVDoll.Modo.EnVivo; joy.altura = 1.70f;
        var kur = Vacio(raiz, "Kuroki", Vector3.zero).AddComponent<BRTVDoll>(); kur.id = "kuroki"; kur.modo = BRTVDoll.Modo.EnVivo; kur.altura = 1.70f;

        // ------------------------------------------------ cámara de programa + post (bloom como la mansión)
        var camGO = new GameObject("CamPrograma"); camGO.tag = "MainCamera";
        var cam = camGO.AddComponent<Camera>(); cam.allowHDR = true; cam.allowMSAA = false; cam.nearClipPlane = 0.05f; cam.farClipPlane = 600; cam.fieldOfView = 40;
        camGO.AddComponent<AudioListener>();
        var ppl = camGO.AddComponent<PostProcessLayer>();
        var res = AssetDatabase.LoadAssetAtPath<PostProcessResources>("Packages/com.unity.postprocessing/PostProcessing/PostProcessResources.asset");
        ppl.Init(res); ppl.volumeLayer = ~0; ppl.volumeTrigger = camGO.transform; ppl.antialiasingMode = PostProcessLayer.Antialiasing.SubpixelMorphologicalAntialiasing;
        var perfil = PerfilPost();
        var vol = new GameObject("PostFX").AddComponent<PostProcessVolume>(); vol.isGlobal = true; vol.priority = 1; vol.sharedProfile = perfil;

        var est = new GameObject("ESTACION").AddComponent<BRTVEstacion>(); est.cam = cam; est.joy = joy; est.kuroki = kur;

        EditorSceneManager.SaveScene(escena, EscenaPath);
        EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(EscenaPath, true) };
        Debug.Log("[BRTV] estación construida: personal=" + personas);
    }

    static PostProcessProfile PerfilPost()
    {
        var path = Raiz + "/PostFX_BRTV.asset";
        AssetDatabase.DeleteAsset(path);
        var p = ScriptableObject.CreateInstance<PostProcessProfile>();
        var bloom = p.AddSettings<Bloom>(); bloom.enabled.Override(true); bloom.intensity.Override(1.6f); bloom.threshold.Override(1.1f); bloom.softKnee.Override(0.6f); bloom.diffusion.Override(7.5f);
        var cg = p.AddSettings<ColorGrading>(); cg.tonemapper.Override(Tonemapper.ACES); cg.postExposure.Override(0.25f); cg.saturation.Override(10f); cg.contrast.Override(14f);
        var ao = p.AddSettings<AmbientOcclusion>(); ao.enabled.Override(true); ao.mode.Override(AmbientOcclusionMode.MultiScaleVolumetricObscurance); ao.intensity.Override(0.9f); ao.color.Override(new Color(0.08f, 0.02f, 0.12f));
        var vig = p.AddSettings<Vignette>(); vig.intensity.Override(0.28f); vig.smoothness.Override(0.4f);
        var ca = p.AddSettings<ChromaticAberration>(); ca.intensity.Override(0.06f);
        AssetDatabase.CreateAsset(p, path);
        foreach (var s in p.settings) { s.name = s.GetType().Name; AssetDatabase.AddObjectToAsset(s, p); }
        AssetDatabase.SaveAssets();
        return p;
    }

    // -------------------------------------------------------------------------------------------- NOTICIARIO + REDACCIÓN + NÚCLEO
    static void Noticiario(Transform raiz)
    {
        // la sala del noticiario se abre hacia atrás: la redacción y el núcleo quedan detrás del vidrio
        var sala = Sala(raiz, "NOTICIARIO", 0, 26, 25, 14, 8.5f, paredFondo: false);
        var t = sala.transform;
        Tarima(t, new Vector3(0, 0, -0.6f), 5.2f, 0.2f, nRosa);
        // escritorio curvo (centro detrás de las conductoras)
        var c = new Vector3(0, 0.2f, -3.0f); float R = 2.55f;
        EscritorioArco(t, "Escritorio", c, R, -52, 52, 0.72f, mPerla, nRosa);
        Box(t, "FrenteLogoPlaca", new Vector3(0, 0.6f, c.z + R + 0.07f), new Vector3(2.7f, 0.36f, 0.02f), mNegro);
        Texto(t, "FrenteLogo", new Vector3(0, 0.6f, c.z + R + 0.09f), "<color=#FF4FB8>BLACK</color>ROSE <size=60%><color=#4BE3FF>NOTICIAS 2049</color></size>", 1.7f, WHITE, 2.6f);
        var ty = new GameObject("x");
        Object.DestroyImmediate(ty);
        // conductoras sentadas: x ±0.75 sobre radio R−0.85
        float rc = R - 0.85f;
        Vector3 pj = new Vector3(-0.78f, 0.2f, c.z + Mathf.Sqrt(rc * rc - 0.78f * 0.78f)), pk = new Vector3(0.78f, 0.2f, pj.z);
        Silla(t, "SillaJoy", pj + new Vector3(0, 0, -0.05f), 0, mNegro, 0.58f, true);
        Silla(t, "SillaKuroki", pk + new Vector3(0, 0, -0.05f), 0, mNegro, 0.58f, true);
        Box(t, "TabletJ", new Vector3(-0.7f, 1.01f, pj.z + 0.55f), new Vector3(0.24f, 0.01f, 0.32f), mNegro, new Vector3(0, 8, 0));
        Box(t, "TabletK", new Vector3(0.7f, 1.01f, pk.z + 0.55f), new Vector3(0.24f, 0.01f, 0.32f), mNegro, new Vector3(0, -8, 0));
        Box(t, "MicJ", new Vector3(-0.35f, 1.08f, pj.z + 0.6f), new Vector3(0.02f, 0.14f, 0.02f), mCromo, new Vector3(20, 0, 0));
        Box(t, "MicK", new Vector3(0.35f, 1.08f, pk.z + 0.6f), new Vector3(0.02f, 0.14f, 0.02f), mCromo, new Vector3(20, 0, 0));

        // muro de video detrás: central (medios/ident) y dos laterales en ángulo
        var mv = Vacio(t, "MuroVideo", new Vector3(0, 0, -5.4f));
        Box(mv.transform, "Marco", new Vector3(0, 2.7f, -0.06f), new Vector3(6.4f, 3.7f, 0.1f), mCromo);
        Quad(mv.transform, "Pantalla_Medio_Noticiario", new Vector3(0, 2.7f, 0.0f), new Vector2(6.1f, 3.43f), tvIdentMedio);
        foreach (var sx in new[] { -1, 1 })
        {
            var lado = Vacio(mv.transform, "Lateral" + sx, new Vector3(sx * 6.4f, 0, 2.9f), new Vector3(0, -sx * 42, 0));
            Box(lado.transform, "Marco", new Vector3(0, 2.7f, -0.06f), new Vector3(3.2f, 3.7f, 0.1f), mCromo);
            Quad(lado.transform, "Pantalla", new Vector3(0, 2.7f, 0), new Vector2(3.0f, 3.45f), sx < 0 ? tvHud : tvTiempo);
            Box(lado.transform, "Pie", new Vector3(0, 0.42f, -0.06f), new Vector3(0.3f, 0.84f, 0.1f), mNegro);
        }
        Texto(mv.transform, "Titulo", new Vector3(0, 4.95f, 0.05f), "BLACKROSE TV · NOTICIAS", 4.6f, PINK * 1.6f, 12);
        Box(mv.transform, "LetreroBarra", new Vector3(0, 4.6f, 0), new Vector3(6.4f, 0.03f, 0.03f), nCian);
        // AL AIRE
        var aire = Vacio(t, "AlAire", new Vector3(5.6f, 4.1f, -4.9f));
        Box(aire.transform, "Caja", Vector3.zero, new Vector3(1.6f, 0.45f, 0.12f), mNegro);
        Texto(aire.transform, "Texto", new Vector3(0, 0, 0.07f), "● AL AIRE", 2.4f, new Color(1, 0.25f, 0.3f), 3);
        var la = Luz(aire.transform, "Brillo", LightType.Point, new Vector3(0, 0, 0.5f), Vector3.zero, RED, 1.2f, 2.5f); la.gameObject.AddComponent<BRTVLatido>();
        // zócalo LED en el frente de la tarima
        var zoc = Texto(t, "TXT_zocalo_noticiario", new Vector3(0, 0.1f, 4.75f), "BLACKROSE TV · SISTEMA AUTÓNOMO DE TRANSMISIÓN · 2049", 1.3f, CYAN * 1.3f, 9);
        zoc.gameObject.AddComponent<BRTVRotador>().items = new[] { "BLACKROSE TV · SISTEMA AUTÓNOMO DE TRANSMISIÓN · 2049", "LA NOTICIA SE ORGANIZA SOLA", "SEÑAL 24/7 · TWITCH · YOUTUBE" };

        // tabiques de vidrio a los lados del muro: se ve la redacción detrás de las conductoras
        for (int sx = -1; sx <= 1; sx += 2)
            for (int i = 0; i < 6; i++)
            {
                float x = sx * (4.1f + i * 1.6f);
                Box(t, "Vidrio" + sx + i, new Vector3(x, 2.4f, -5.6f), new Vector3(1.55f, 4.8f, 0.04f), mVidrio);
                Box(t, "Montante" + sx + i, new Vector3(x + sx * 0.8f, 2.4f, -5.6f), new Vector3(0.06f, 4.8f, 0.08f), mCromo);
            }
        Box(t, "VidrioAlto", new Vector3(0, 6.5f, -5.6f), new Vector3(26, 3.4f, 0.04f), mVidrio);
        Box(t, "VigaVidrio", new Vector3(0, 4.82f, -5.6f), new Vector3(26, 0.1f, 0.12f), mCromo);
        Box(t, "VigaNeon", new Vector3(0, 4.76f, -5.52f), new Vector3(26, 0.02f, 0.02f), nViol);

        // ---------------- redacción: tres filas de puestos a cada lado, con personal trabajando
        var red = Vacio(t, "REDACCION", new Vector3(0, 0, -6));
        int k = 0;
        for (int fila = 0; fila < 3; fila++)          // columnas a cada lado del pasillo central; miran hacia el núcleo/pasillo
            for (int sx = -1; sx <= 1; sx += 2)
                for (int j = 0; j < 2; j++)
                {
                    float x = sx * (5.0f + j * 2.7f), z = -2.4f - fila * 2.6f;
                    bool persona = (k % 3) != 2;     // dos de cada tres puestos ocupados
                    Puesto(red.transform, $"Puesto_{fila}_{sx}_{j}", new Vector3(x, 0, z), (sx < 0 ? 90 : -90) + (fila - 1) * 6, k, persona);
                    k++;
                }
        // muro de monitores de la redacción (control de señales)
        var mm = Vacio(red.transform, "MuroMonitores", new Vector3(-9.5f, 0, -13.5f), new Vector3(0, 35, 0));
        for (int fx = 0; fx < 4; fx++) for (int fy = 0; fy < 3; fy++)
            {
                Box(mm.transform, $"M{fx}{fy}", new Vector3(fx * 1.25f - 1.9f, 1.3f + fy * 0.75f, -0.03f), new Vector3(1.2f, 0.7f, 0.05f), mNegro);
                var mats = new[] { tvHud, tvTiempo, tvCancha, tvTactico, tvBimbo, tvSynth, tvIdent, tvHud2 };
                Quad(mm.transform, $"P{fx}{fy}", new Vector3(fx * 1.25f - 1.9f, 1.3f + fy * 0.75f, 0), new Vector2(1.14f, 0.64f), mats[(fx * 3 + fy) % mats.Length]);
            }
        Texto(mm.transform, "Rotulo", new Vector3(0, 3.6f, 0), "CONTROL DE SEÑALES", 2f, CYAN * 1.4f, 6);
        Persona(mm.transform, "Supervisora", new Vector3(0.6f, 0, 1.6f), 180, BRTVDoll.Modo.Parada, 1.7f);

        // ---------------- NÚCLEO: donde se generan las noticias (columna de datos autoorganizada)
        var nu = Vacio(t, "NUCLEO", new Vector3(0, 0, -16f));
        Tarima(nu.transform, Vector3.zero, 3.2f, 0.3f, nCian);
        Cyl(nu.transform, "Columna", new Vector3(0, 4.4f, 0), new Vector3(2.4f, 4.1f, 2.4f), mVidrio);
        Cyl(nu.transform, "Alma", new Vector3(0, 4.4f, 0), new Vector3(0.5f, 4.1f, 0.5f), Neon("Nucleo_Alma", new Color(0.55f, 0.35f, 1f), 5f));
        Cyl(nu.transform, "AlmaHalo", new Vector3(0, 4.4f, 0), new Vector3(0.9f, 4.1f, 0.9f), mHolo);
        Cyl(nu.transform, "Tapa", new Vector3(0, 8.45f, 0), new Vector3(3.0f, 0.06f, 3.0f), mCromo);
        for (int i = 0; i < 5; i++)
        {
            var anillo = MeshGO(nu.transform, "Anillo" + i, toroMesh, new Vector3(0, 1.4f + i * 1.45f, 0), Vector3.one * (1.45f + 0.12f * (i % 2)), i % 2 == 0 ? nRosa : nCian, new Vector3(i * 7, 0, i * 5));
            var g = anillo.AddComponent<BRTVGiro>(); g.eje = new Vector3(0.1f * (i - 2), 1, 0.08f); g.vel = (i % 2 == 0 ? 1 : -1) * (18 + i * 6); g.flota = 0.08f; g.flotaVel = 0.7f + i * 0.13f;
        }
        var orb = Vacio(nu.transform, "Orbita", new Vector3(0, 0, 0)); var og = orb.AddComponent<BRTVGiro>(); og.vel = 6;
        for (int i = 0; i < 6; i++)
        {
            float a = i * 60 * Mathf.Deg2Rad; var pos = new Vector3(Mathf.Sin(a) * 4.2f, 3.0f + (i % 2) * 0.9f, Mathf.Cos(a) * 4.2f);
            var hp = Vacio(orb.transform, "HoloPanel" + i, pos); hp.transform.localRotation = Quaternion.LookRotation(new Vector3(pos.x, 0, pos.z));
            Quad(hp.transform, "Pantalla", Vector3.zero, new Vector2(1.9f, 1.05f), i % 2 == 0 ? tvHud2 : tvTactico);
            Texto(hp.transform, "TXT_titular_" + i, new Vector3(0, -0.75f, 0.02f), new[] { "REDACCIÓN AUTÓNOMA EN LÍNEA", "TENDENCIAS DEL DÍA", "RSS · 214 FUENTES", "AGENDA 12:00 → 12:00", "CHAT EN VIVO", "SEÑAL ESTABLE" }[i], 1.5f, WHITE, 4);
        }
        Texto(nu.transform, "Lema", new Vector3(0, 8.9f, 3.1f), "SISTEMA AUTÓNOMO DE TRANSMISIÓN · AUTOORGANIZADO", 3f, CYAN * 1.5f, 16);
        // partículas de datos que suben
        var ps = Vacio(nu.transform, "Datos", new Vector3(0, 0.3f, 0)).AddComponent<ParticleSystem>();
        var main = ps.main; main.startLifetime = 5; main.startSpeed = 1.6f; main.startSize = 0.06f; main.maxParticles = 500; main.startColor = new ParticleSystem.MinMaxGradient(new Color(0.4f, 0.9f, 1f), new Color(1f, 0.3f, 0.8f));
        var em = ps.emission; em.rateOverTime = 70;
        var sh = ps.shape; sh.shapeType = ParticleSystemShapeType.Cone; sh.angle = 2; sh.radius = 1.0f; sh.rotation = new Vector3(-90, 0, 0);
        var pr = ps.GetComponent<ParticleSystemRenderer>(); pr.sharedMaterial = Aditivo("Particula_Datos", new Color(1, 1, 1, 0.8f));
        var dm = AssetDatabase.GetBuiltinExtraResource<Material>("Default-Particle.mat"); if (dm != null) pr.sharedMaterial.mainTexture = dm.mainTexture;
        var ln = Luz(nu.transform, "LuzNucleo", LightType.Point, new Vector3(0, 3.5f, 0), Vector3.zero, new Color(0.55f, 0.4f, 1f), 3.5f, 14); ln.gameObject.AddComponent<BRTVLatido>().vel = 1.2f;
        // holomesa detrás del núcleo con dos editoras
        var hm = Vacio(nu.transform, "Holomesa", new Vector3(0, 0, -4.6f));
        Cyl(hm.transform, "Mesa", new Vector3(0, 0.45f, 0), new Vector3(2.6f, 0.45f, 2.6f), mNegro);
        Cyl(hm.transform, "Borde", new Vector3(0, 0.9f, 0), new Vector3(2.7f, 0.02f, 2.7f), nCian);
        Quad(hm.transform, "Superficie", new Vector3(0, 0.915f, 0), new Vector2(1.8f, 1.8f), tvTactico, new Vector3(90, 0, 0));
        var holo = Esf(hm.transform, "Holo", new Vector3(0, 1.55f, 0), 0.7f, mHolo); var hg = holo.AddComponent<BRTVGiro>(); hg.vel = 25; hg.flota = 0.05f;
        MeshGO(hm.transform, "HoloAnillo", toroFino, new Vector3(0, 1.55f, 0), Vector3.one * 0.55f, nCian, new Vector3(70, 0, 0)).AddComponent<BRTVGiro>().vel = -40;
        Persona(hm.transform, "EditoraA", new Vector3(-0.9f, 0, -1.55f), 30, BRTVDoll.Modo.Holomesa, 1.68f);
        Persona(hm.transform, "EditoraB", new Vector3(1.0f, 0, 1.5f), 200, BRTVDoll.Modo.Holomesa, 1.64f);

        // ventanal del fondo: la ciudad 2049
        for (int i = -6; i <= 6; i++) Box(t, "Ventanal" + i, new Vector3(i * 2.1f, 4.25f, -24.9f), new Vector3(0.1f, 8.5f, 0.15f), mCromo);
        Box(t, "VentanalAlto", new Vector3(0, 8.4f, -24.9f), new Vector3(26, 0.2f, 0.2f), mCromo);
        Box(t, "VentanalBajo", new Vector3(0, 0.5f, -24.9f), new Vector3(26, 1f, 0.2f), mNegro);
        Box(t, "VentanalNeon", new Vector3(0, 1.02f, -24.8f), new Vector3(26, 0.03f, 0.03f), nRosa);

        // ---------------- luces
        Foco(t, "LlaveJoy", new Vector3(-2.2f, 6.8f, 4.5f), pj + Vector3.up * 1.3f, new Color(1f, 0.92f, 0.95f), 2.6f, false, true, 32);
        Foco(t, "LlaveKuroki", new Vector3(2.2f, 6.8f, 4.5f), pk + Vector3.up * 1.3f, new Color(1f, 0.92f, 0.95f), 2.6f, false, false, 32);
        Foco(t, "ContraRosa", new Vector3(-3.5f, 7.4f, -4.4f), new Vector3(-0.6f, 1.2f, -1f), PINK, 4f, true);
        Foco(t, "ContraCian", new Vector3(3.5f, 7.4f, -4.4f), new Vector3(0.6f, 1.2f, -1f), CYAN, 4f, true);
        Foco(t, "Ambiente1", new Vector3(-8f, 7.4f, 2f), new Vector3(-5, 0, -1), VIOL, 4f, true);
        Foco(t, "Ambiente2", new Vector3(8f, 7.4f, 2f), new Vector3(5, 0, -1), PINK, 4f, true);
        Luz(t, "Redaccion1", LightType.Point, new Vector3(-6.3f, 3.6f, -10), Vector3.zero, new Color(0.85f, 0.75f, 1f), 3.2f, 11);
        Luz(t, "Redaccion2", LightType.Point, new Vector3(6.3f, 3.6f, -10), Vector3.zero, new Color(0.85f, 0.75f, 1f), 3.2f, 11);
        Luz(t, "Redaccion3", LightType.Point, new Vector3(-9.5f, 3f, -16), Vector3.zero, CYAN, 2f, 8);
        Luz(t, "Muro", LightType.Point, new Vector3(0, 2.7f, -3.8f), Vector3.zero, new Color(0.9f, 0.5f, 1f), 1.6f, 6);

        // cámaras de estudio (atrezo) con camarógrafas
        CamaraEstudio(t, "CamEstudio1", new Vector3(-3.2f, 0, 5.2f), new Vector3(0, 0, -1), true);
        CamaraEstudio(t, "CamEstudio2", new Vector3(3.4f, 0, 5.6f), new Vector3(0, 0, -1), false);
        CamaraEstudio(t, "CamEstudio3", new Vector3(6.5f, 0, 5.5f), new Vector3(0, 0, -1), true);

        // ---------------- set y planos
        var s = Set(sala, "noticiario", "NOTICIARIO", true, 0.58f, pj, 0, pk, 0);
        Plano(s, "amplio", new Vector3(0, 2.4f, 8.6f), new Vector3(0, 1.6f, -3), 50);
        Plano(s, "dos", new Vector3(0, 1.5f, 3.9f), new Vector3(0, 1.3f, pj.z), 40);
        Plano(s, "joy", new Vector3(-0.25f, 1.45f, 1.6f), pj + new Vector3(0, 1.22f, 0), 27, "joy", 0.08f);
        Plano(s, "kuroki", new Vector3(0.25f, 1.45f, 1.6f), pk + new Vector3(0, 1.22f, 0), 27, "kuroki", 0.08f);
        Plano(s, "lateral", new Vector3(-4.6f, 1.9f, 3.4f), new Vector3(1.2f, 1.3f, -5.5f), 44);
        Plano(s, "lateral_b", new Vector3(6.4f, 2.4f, 3.0f), new Vector3(-0.8f, 1.2f, -4.0f), 42);
        Plano(s, "redaccion", new Vector3(8.5f, 3.4f, -6.6f), new Vector3(-2.5f, 1.4f, -15), 52, "", 0.5f);
        Plano(s, "nucleo", new Vector3(-2.5f, 1.3f, -9.4f), new Vector3(0, 4.6f, -16), 58, "", 0.3f);
        Plano(s, "grua", new Vector3(5.5f, 6.4f, 7.5f), new Vector3(-0.5f, 0.8f, -6), 52, "", 0.6f);
    }

    // -------------------------------------------------------------------------------------------- EL TIEMPO
    static void Tiempo(Transform raiz, float x)
    {
        var sala = Sala(raiz, "EL_TIEMPO", x, 22, 7, 13); var t = sala.transform;
        Tarima(t, new Vector3(0, 0, -0.5f), 4.6f, 0.12f, nCian);
        // muro del tiempo curvo en tres paños
        for (int i = -1; i <= 1; i++)
        {
            var p = Vacio(t, "Muro" + i, new Vector3(i * 4.1f, 0, -4.4f + Mathf.Abs(i) * 0.9f), new Vector3(0, -i * 22, 0));
            Box(p.transform, "Marco", new Vector3(0, 2.6f, -0.06f), new Vector3(4.3f, 3.9f, 0.1f), mCromo);
            Quad(p.transform, i == 0 ? "Pantalla_Medio_Tiempo" : "Pantalla", new Vector3(0, 2.6f, 0), new Vector2(4.1f, 3.7f), i == 0 ? tvTiempo : (i < 0 ? tvTiempo : tvHud2));
        }
        Texto(t, "Titulo", new Vector3(0, 5.05f, -4.3f), "EL TIEMPO <color=#FF4FB8>2049</color>", 5f, WHITE, 12);
        string[] ciudades = { "SANTIAGO  24°", "VALPARAÍSO  19°", "TOKIO  12°", "PUNTA ARENAS  6°", "BASE MARTE I  −63°" };
        for (int i = 0; i < ciudades.Length; i++)
        {
            var row = Vacio(t, "Ciudad" + i, new Vector3(-4.3f, 3.9f - i * 0.55f, -2.6f), new Vector3(0, -22, 0));
            Box(row.transform, "Placa", Vector3.zero, new Vector3(2.4f, 0.42f, 0.02f), Transp("Placa_Tiempo", new Color(0.05f, 0.02f, 0.1f, 0.65f), 0.9f));
            Box(row.transform, "Linea", new Vector3(-1.18f, 0, 0.012f), new Vector3(0.04f, 0.42f, 0.01f), i == 4 ? nRojo : nCian);
            Texto(row.transform, "Txt", new Vector3(0.05f, 0, 0.02f), ciudades[i], 1.7f, WHITE, 2.4f);
        }
        // holoplaneta
        var gl = Vacio(t, "HoloPlaneta", new Vector3(3.6f, 0, 0.2f));
        Cyl(gl.transform, "Pedestal", new Vector3(0, 0.45f, 0), new Vector3(0.9f, 0.45f, 0.9f), mCromo);
        Cyl(gl.transform, "Emisor", new Vector3(0, 0.91f, 0), new Vector3(0.75f, 0.01f, 0.75f), nCian);
        var esfera = Vacio(gl.transform, "Giro", new Vector3(0, 1.85f, 0)); var g1 = esfera.AddComponent<BRTVGiro>(); g1.vel = 12; g1.flota = 0.04f;
        Esf(esfera.transform, "Tierra", Vector3.zero, 1.3f, TV("TV_Planeta", 5, 2f, 1.7f, 1.2f));
        Esf(esfera.transform, "Nubes", Vector3.zero, 1.36f, AditivoPlano("Holo_Tenue", new Color(0.2f, 0.85f, 1f, 0.07f)));
        MeshGO(esfera.transform, "Ecuador", toroFino, Vector3.zero, Vector3.one * 0.7f, nCian);
        MeshGO(esfera.transform, "Meridiano", toroFino, Vector3.zero, Vector3.one * 0.69f, nViol, new Vector3(90, 0, 0));
        var orb = MeshGO(gl.transform, "Orbita", toroFino, new Vector3(0, 1.85f, 0), Vector3.one * 1.05f, nRosa, new Vector3(18, 0, 10)); orb.AddComponent<BRTVGiro>().vel = 30;
        Esf(orb.transform, "Satelite", new Vector3(1, 0, 0), 0.06f, nRosa);
        // personal: productora de piso con tablet
        Persona(t, "Productora", new Vector3(-8.2f, 0, 3.5f), 140, BRTVDoll.Modo.Parada, 1.66f);
        CamaraEstudio(t, "CamEstudio1", new Vector3(-1.5f, 0, 6.0f), new Vector3(0, 0, -1), true);
        CamaraEstudio(t, "CamEstudio2", new Vector3(3.5f, 0, 6.2f), new Vector3(1, 0, -1), false);
        Foco(t, "Llave", new Vector3(-1.0f, 6.4f, 4.5f), new Vector3(-1, 1.3f, 0.4f), new Color(1f, 0.95f, 0.97f), 2.8f, false, true, 30);
        Foco(t, "LlaveK", new Vector3(3.0f, 6.4f, 5.0f), new Vector3(2.15f, 1.3f, 0.9f), new Color(1f, 0.92f, 0.97f), 3.0f, false, false, 26);
        Foco(t, "Contra", new Vector3(0, 6.8f, -3.5f), new Vector3(-0.5f, 1.2f, 0.5f), CYAN, 5f, true);
        Foco(t, "Planeta", new Vector3(5f, 6.8f, 2f), new Vector3(3.6f, 1.6f, 0.2f), VIOL, 4f, true);
        Luz(t, "Muro", LightType.Point, new Vector3(0, 2.6f, -2.6f), Vector3.zero, new Color(0.4f, 0.6f, 1f), 1.8f, 7);

        var s = Set(sala, "tiempo", "EL TIEMPO", false, 0.5f, new Vector3(-1.1f, 0.12f, 0.4f), 12, new Vector3(2.15f, 0.12f, 0.9f), -25);
        Plano(s, "amplio", new Vector3(0, 2.3f, 9.5f), new Vector3(0, 2.2f, -3), 48);
        Plano(s, "joy", new Vector3(-0.4f, 1.5f, 3.4f), new Vector3(-1.1f, 1.35f, 0.4f), 30, "joy", 0.1f);
        Plano(s, "kuroki", new Vector3(1.2f, 1.5f, 3.6f), new Vector3(2.15f, 1.35f, 0.9f), 30, "kuroki", 0.1f);
        Plano(s, "mapa", new Vector3(-4.5f, 1.8f, 4.2f), new Vector3(1, 2.4f, -4), 46);
        Plano(s, "planeta", new Vector3(5.6f, 1.9f, 3.0f), new Vector3(3.6f, 1.8f, 0.2f), 34, "", 0.15f);
    }

    // -------------------------------------------------------------------------------------------- DEPORTES
    static void Deportes(Transform raiz, float x)
    {
        var sala = Sala(raiz, "DEPORTES", x, 22, 7, 13); var t = sala.transform;
        Tarima(t, new Vector3(0, 0, -0.5f), 4.8f, 0.18f, nVerde);
        // escritorio angular
        var d = Vacio(t, "Escritorio", new Vector3(0, 0.18f, -0.4f));
        Box(d.transform, "Centro", new Vector3(0, 0.36f, 0), new Vector3(3.0f, 0.72f, 0.7f), mNegro);
        Box(d.transform, "AlaI", new Vector3(-1.95f, 0.36f, -0.45f), new Vector3(1.2f, 0.72f, 0.7f), mNegro, new Vector3(0, 35, 0));
        Box(d.transform, "AlaD", new Vector3(1.95f, 0.36f, -0.45f), new Vector3(1.2f, 0.72f, 0.7f), mNegro, new Vector3(0, -35, 0));
        Box(d.transform, "Cubierta", new Vector3(0, 0.74f, -0.05f), new Vector3(3.1f, 0.05f, 0.85f), mCromo);
        Box(d.transform, "NeonV", new Vector3(0, 0.25f, 0.36f), new Vector3(3.0f, 0.04f, 0.01f), nVerde);
        Box(d.transform, "NeonV2", new Vector3(0, 0.7f, 0.36f), new Vector3(3.0f, 0.015f, 0.01f), nOro);
        Texto(d.transform, "Logo", new Vector3(0, 0.47f, 0.37f), "BRTV <color=#7DFFC4>DEPORTES</color>", 2.4f, WHITE, 3);
        // balón holográfico sobre el escritorio
        var bal = Esf(d.transform, "HoloBalon", new Vector3(0, 1.55f, -0.05f), 0.32f, mHolo); var bg = bal.AddComponent<BRTVGiro>(); bg.eje = new Vector3(0.3f, 1, 0.2f); bg.vel = 60; bg.flota = 0.05f;
        MeshGO(bal.transform, "Costura", toroFino, Vector3.zero, Vector3.one * 0.52f, nVerde, new Vector3(90, 0, 0));
        // muro LED de cancha + pilares marcadores
        Box(t, "MarcoLED", new Vector3(0, 2.6f, -5.0f), new Vector3(9.2f, 4.0f, 0.1f), mCromo);
        Quad(t, "Pantalla_Medio_Deportes", new Vector3(0, 2.6f, -4.94f), new Vector2(9.0f, 3.8f), tvCancha);
        Texto(t, "Marcador", new Vector3(0, 4.95f, -4.9f), "NEO SANTIAGO <color=#7DFFC4>2</color> · <color=#FF4FB8>1</color> ORBITAL TOKIO", 3.2f, WHITE, 12);
        for (int sx = -1; sx <= 1; sx += 2)
        {
            Box(t, "Pilar" + sx, new Vector3(sx * 5.8f, 2.5f, -4.4f), new Vector3(0.9f, 5f, 0.5f), mNegro);
            Quad(t, "PilarEQ" + sx, new Vector3(sx * 5.8f, 2.5f, -4.14f), new Vector2(0.75f, 4.6f), tvEQ);
        }
        // vitrina de trofeos
        for (int i = 0; i < 3; i++)
        {
            var tr = Vacio(t, "Trofeo" + i, new Vector3(-8.2f + i * 1.2f, 0, -3.5f));
            Box(tr.transform, "Pedestal", new Vector3(0, 0.55f, 0), new Vector3(0.7f, 1.1f, 0.7f), mPerla);
            Box(tr.transform, "PedNeon", new Vector3(0, 1.11f, 0), new Vector3(0.72f, 0.02f, 0.72f), nOro);
            Cyl(tr.transform, "Base", new Vector3(0, 1.2f, 0), new Vector3(0.25f, 0.08f, 0.25f), mNegro);
            Cyl(tr.transform, "Tallo", new Vector3(0, 1.45f, 0), new Vector3(0.07f, 0.18f, 0.07f), mOro);
            Esf(tr.transform, "Copa", new Vector3(0, 1.75f, 0), 0.34f - i * 0.04f, mOro);
            Box(tr.transform, "Vitrina", new Vector3(0, 1.65f, 0), new Vector3(0.7f, 1.1f, 0.7f), mVidrio);
        }
        Luz(t, "Trofeos", LightType.Point, new Vector3(-7f, 2.6f, -2.5f), Vector3.zero, GOLD, 2f, 5);
        Persona(t, "Estadistica", new Vector3(8.0f, 0, -2.0f), 220, BRTVDoll.Modo.Parada, 1.64f);
        Puesto(t, "PuestoStats", new Vector3(7.6f, 0, 2.5f), 250, 4, true);
        CamaraEstudio(t, "CamEstudio1", new Vector3(-2.5f, 0, 5.5f), new Vector3(0, 0, -1), true);
        CamaraEstudio(t, "CamEstudio2", new Vector3(2.8f, 0, 5.8f), new Vector3(0, 0, -1), false);
        Foco(t, "LlaveA", new Vector3(-2f, 6.6f, 4.2f), new Vector3(-0.7f, 1.3f, -0.9f), new Color(1f, 0.96f, 0.92f), 2.8f, false, true, 30);
        Foco(t, "LlaveB", new Vector3(2f, 6.6f, 4.2f), new Vector3(0.7f, 1.3f, -0.9f), new Color(1f, 0.96f, 0.92f), 2.6f, false, false, 30);
        Foco(t, "ContraV", new Vector3(-3f, 6.8f, -3.8f), new Vector3(-0.7f, 1.2f, -0.9f), GREEN, 5f, true);
        Foco(t, "ContraO", new Vector3(3f, 6.8f, -3.8f), new Vector3(0.7f, 1.2f, -0.9f), GOLD, 5f, true);

        var s = Set(sala, "deportes", "DEPORTES", true, 0.58f, new Vector3(-0.72f, 0.18f, -1.25f), 0, new Vector3(0.72f, 0.18f, -1.25f), 0);
        Silla(t, "SillaJ", new Vector3(-0.72f, 0.18f, -1.3f), 0, mNegro, 0.58f, true);
        Silla(t, "SillaK", new Vector3(0.72f, 0.18f, -1.3f), 0, mNegro, 0.58f, true);
        Plano(s, "amplio", new Vector3(0, 2.6f, 9.2f), new Vector3(0, 1.9f, -3), 48);
        Plano(s, "dos", new Vector3(0, 1.5f, 3.6f), new Vector3(0, 1.25f, -1.25f), 38);
        Plano(s, "joy", new Vector3(-0.2f, 1.5f, 1.9f), new Vector3(-0.72f, 1.42f, -1.25f), 27, "joy", 0.08f);
        Plano(s, "kuroki", new Vector3(0.2f, 1.5f, 1.9f), new Vector3(0.72f, 1.42f, -1.25f), 27, "kuroki", 0.08f);
        Plano(s, "lateral", new Vector3(6.0f, 2.2f, 4.0f), new Vector3(-1.5f, 1.4f, -2.5f), 44);
        Plano(s, "trofeos", new Vector3(-5.5f, 1.7f, 0.5f), new Vector3(-7.4f, 1.5f, -3.5f), 40, "", 0.15f);
    }

    // -------------------------------------------------------------------------------------------- PANEL DE CONVERSACIÓN
    static void Panel(Transform raiz, float x)
    {
        var sala = Sala(raiz, "PANEL", x, 22, 7, 13); var t = sala.transform;
        Cyl(t, "Alfombra", new Vector3(0, 0.01f, 0), new Vector3(7.5f, 0.01f, 7.5f), mLavanda);
        Cyl(t, "AlfombraAro", new Vector3(0, 0.005f, 0), new Vector3(7.7f, 0.005f, 7.7f), nViol);
        // arcos de neón concéntricos en el fondo
        for (int i = 0; i < 4; i++)
            MeshGO(t, "Arco" + i, toroMesh, new Vector3(0, 0, -5.6f), Vector3.one * (2.2f + i * 0.9f), i % 2 == 0 ? nRosa : nViol, new Vector3(90, 0, 0));
        Box(t, "TapaArcos", new Vector3(0, -2.5f, -5.6f), new Vector3(12, 5, 1), mNegro);   // corta la mitad de abajo de los aros
        Quad(t, "Pantalla_Medio_Panel", new Vector3(0, 2.0f, -6.7f), new Vector2(3.4f, 1.9f), tvIdentMedio);
        Texto(t, "Titulo", new Vector3(0, 3.35f, -6.6f), "EL <color=#FF4FB8>PANEL</color> · CONVERSACIÓN 2049", 2.6f, WHITE, 10);
        for (int sx = -1; sx <= 1; sx += 2)
        {
            Quad(t, "Lateral" + sx, new Vector3(sx * 7.0f, 2.6f, -4.2f), new Vector2(3.2f, 1.8f), tvSynth, new Vector3(0, 180 - sx * 25, 0));
            Box(t, "LateralMarco" + sx, new Vector3(sx * 7.02f, 2.6f, -4.25f), new Vector3(3.35f, 1.95f, 0.05f), mCromo, new Vector3(0, -sx * 25, 0));
        }
        // mesa ratona + sillones en media luna
        Cyl(t, "Mesa", new Vector3(0, 0.22f, 0.35f), new Vector3(1.6f, 0.22f, 1.6f), mNegro);
        Cyl(t, "MesaTapa", new Vector3(0, 0.45f, 0.35f), new Vector3(1.7f, 0.02f, 1.7f), mVidrio);
        Cyl(t, "MesaNeon", new Vector3(0, 0.44f, 0.35f), new Vector3(1.72f, 0.01f, 1.72f), nRosa);
        Cyl(t, "Florero", new Vector3(0, 0.6f, 0.35f), new Vector3(0.14f, 0.14f, 0.14f), mCromo);
        for (int i = 0; i < 5; i++) Esf(t, "Rosa" + i, new Vector3(Mathf.Sin(i * 1.3f) * 0.05f, 0.78f + (i % 2) * 0.04f, 0.35f + Mathf.Cos(i * 1.3f) * 0.05f), 0.055f, mVelvet);
        Vector3 pj = new Vector3(-1.75f, 0, -0.35f), pk = new Vector3(1.75f, 0, -0.35f);
        Sillon(t, "SillonJoy", pj, 35, mVelvet); Sillon(t, "SillonKuroki", pk, -35, mVelvet);
        Sillon(t, "SillonInvitada1", new Vector3(-0.7f, 0, -1.6f), 10, mRosa); Sillon(t, "SillonInvitada2", new Vector3(0.7f, 0, -1.6f), -10, mRosa);
        Persona(t, "Asistente", new Vector3(-8.0f, 0, 2.5f), 120, BRTVDoll.Modo.Parada, 1.66f);
        CamaraEstudio(t, "CamEstudio1", new Vector3(-3.5f, 0, 5.0f), new Vector3(0, 0, -0.5f), true);
        CamaraEstudio(t, "CamEstudio2", new Vector3(3.5f, 0, 5.0f), new Vector3(0, 0, -0.5f), false);
        Foco(t, "Llave", new Vector3(0, 6.6f, 4.5f), new Vector3(0, 1.0f, -0.6f), new Color(1f, 0.9f, 0.95f), 3f, false, true, 40);
        Foco(t, "ContraR", new Vector3(-3.5f, 6.8f, -4f), new Vector3(-1.5f, 1, -0.3f), PINK, 5f, true);
        Foco(t, "ContraV", new Vector3(3.5f, 6.8f, -4f), new Vector3(1.5f, 1, -0.3f), VIOL, 5f, true);
        Luz(t, "Arcos", LightType.Point, new Vector3(0, 2.5f, -4.5f), Vector3.zero, PINK, 2f, 6);

        var s = Set(sala, "panel", "PANEL DE CONVERSACIÓN", true, 0.44f, pj, 35, pk, -35);
        Plano(s, "amplio", new Vector3(0, 2.2f, 8.4f), new Vector3(0, 1.2f, -2), 46);
        Plano(s, "dos", new Vector3(0, 1.3f, 4.2f), new Vector3(0, 1.0f, -0.6f), 40);
        Plano(s, "joy", new Vector3(0.9f, 1.25f, 1.6f), pj + new Vector3(0, 1.0f, 0), 28, "joy", 0.08f);
        Plano(s, "kuroki", new Vector3(-0.9f, 1.25f, 1.6f), pk + new Vector3(0, 1.0f, 0), 28, "kuroki", 0.08f);
        Plano(s, "picado", new Vector3(4.5f, 4.6f, 4.5f), new Vector3(0, 0.6f, -0.5f), 44, "", 0.4f);
    }

    // -------------------------------------------------------------------------------------------- ENTREVISTAS POLÍTICAS + ANÁLISIS MILITAR
    static void EntrevistasMilitar(Transform raiz, float x)
    {
        var sala = Sala(raiz, "ENTREVISTAS_MILITAR", x, 30, 7, 13); var t = sala.transform;
        Box(t, "Division", new Vector3(0.5f, 2.5f, -4.2f), new Vector3(0.3f, 5f, 5.6f), mNegro);
        Box(t, "DivisionNeon", new Vector3(0.5f, 5.02f, -4.2f), new Vector3(0.32f, 0.03f, 5.6f), nBlanco);

        // ---- entrevista política (izquierda, centro x = −7)
        var e = Vacio(t, "ENTREVISTA", new Vector3(-7, 0, 0));
        Box(e.transform, "Fondo", new Vector3(0, 2.8f, -6.4f), new Vector3(12, 5.6f, 0.2f), Std("Azul_Noche", "#0B1030", 0.2f, 0.6f));
        for (int i = -3; i <= 3; i++)
        {
            Box(e.transform, "Columna" + i, new Vector3(i * 1.6f, 2.6f, -6.2f), new Vector3(0.12f, 4.6f, 0.06f), i == 0 ? nRosa : nBlanco);
        }
        Box(e.transform, "Placa", new Vector3(0, 4.5f, -6.15f), new Vector3(5.4f, 0.7f, 0.04f), mNegro);
        Texto(e.transform, "Titulo", new Vector3(0, 4.5f, -6.1f), "ENTREVISTA · <color=#FF4FB8>PODER 2049</color>", 3.2f, WHITE, 6);
        Quad(e.transform, "Pantalla_Medio_Entrevista", new Vector3(0, 2.3f, -6.15f), new Vector2(2.8f, 1.58f), tvIdentMedio);
        Cyl(e.transform, "Alfombra", new Vector3(0, 0.01f, -0.2f), new Vector3(5.5f, 0.01f, 5.5f), Std("Alfombra_Azul", "#141A40", 0f, 0.2f));
        Cyl(e.transform, "Mesita", new Vector3(0, 0.3f, -0.6f), new Vector3(0.7f, 0.3f, 0.7f), mCromo);
        Cyl(e.transform, "MesitaTapa", new Vector3(0, 0.61f, -0.6f), new Vector3(0.8f, 0.02f, 0.8f), mVidrio);
        Cyl(e.transform, "Vaso1", new Vector3(-0.15f, 0.69f, -0.55f), new Vector3(0.07f, 0.07f, 0.07f), mVidrio);
        Cyl(e.transform, "Vaso2", new Vector3(0.15f, 0.69f, -0.65f), new Vector3(0.07f, 0.07f, 0.07f), mVidrio);
        Vector3 ej = new Vector3(-8.25f, 0, -0.4f), ek = new Vector3(-5.75f, 0, -0.4f);
        Sillon(e.transform, "SillonEntrevistadora", ej - e.transform.localPosition, 62, mCuero);
        Sillon(e.transform, "SillonInvitada", ek - e.transform.localPosition, -62, mCuero);
        Foco(e.transform, "Llave", new Vector3(0, 6.5f, 4.0f), new Vector3(0, 1.0f, -0.4f), new Color(1f, 0.95f, 0.9f), 3.2f, false, true, 38);
        Foco(e.transform, "ContraA", new Vector3(-4f, 6.6f, -4f), new Vector3(-1.2f, 1, -0.4f), new Color(0.4f, 0.55f, 1f), 5f, true);
        Foco(e.transform, "ContraB", new Vector3(4f, 6.6f, -4f), new Vector3(1.2f, 1, -0.4f), PINK, 4f, true);
        CamaraEstudio(e.transform, "CamEstudio1", new Vector3(-2.8f, 0, 4.6f), new Vector3(0.5f, 0, -0.5f), true);

        var s1 = Set(sala, "entrevistas", "ENTREVISTAS POLÍTICAS", true, 0.44f, ej, 62, ek, -62);
        Plano(s1, "amplio", new Vector3(-7, 2.0f, 7.8f), new Vector3(-7, 1.4f, -2), 44);
        Plano(s1, "dos", new Vector3(-7, 1.2f, 3.6f), new Vector3(-7, 1.0f, -0.5f), 40);
        Plano(s1, "joy", new Vector3(-5.2f, 1.2f, 1.3f), ej + new Vector3(0, 1.0f, 0), 30, "joy", 0.06f);
        Plano(s1, "kuroki", new Vector3(-8.8f, 1.2f, 1.3f), ek + new Vector3(0, 1.0f, 0), 30, "kuroki", 0.06f);
        Plano(s1, "perfil", new Vector3(-7f, 3.2f, 4.5f), new Vector3(-7f, 0.8f, -0.6f), 42, "", 0.3f);

        // ---- análisis militar (derecha, centro x = +7)
        var m = Vacio(t, "MILITAR", new Vector3(7.5f, 0, 0));
        Box(m.transform, "Fondo", new Vector3(0, 2.8f, -6.4f), new Vector3(13, 5.6f, 0.2f), Std("Gris_Tactico", "#0A0F12", 0.3f, 0.5f));
        for (int i = -1; i <= 1; i++)
        {
            Box(m.transform, "PantMarco" + i, new Vector3(i * 4.0f, 2.8f, -6.25f), new Vector3(3.8f, 2.3f, 0.06f), mNegro);
            Quad(m.transform, i == 0 ? "Pantalla_Medio_Militar" : "Pantalla" + i, new Vector3(i * 4.0f, 2.8f, -6.2f), new Vector2(3.6f, 2.1f), i == 0 ? tvTactico : tvHud2);
        }
        Texto(m.transform, "Titulo", new Vector3(0, 4.6f, -6.2f), "ANÁLISIS MILITAR · <color=#7DFFC4>TECNOLOGÍA Y DEFENSA</color>", 3f, WHITE, 12);
        // holomesa táctica
        Box(m.transform, "Mesa", new Vector3(0, 0.45f, -0.4f), new Vector3(4.0f, 0.9f, 2.4f), mNegro);
        Box(m.transform, "MesaBorde", new Vector3(0, 0.91f, -0.4f), new Vector3(4.1f, 0.03f, 2.5f), nVerde);
        Quad(m.transform, "MesaPantalla", new Vector3(0, 0.93f, -0.4f), new Vector2(3.9f, 2.3f), tvTactico, new Vector3(90, 0, 0));
        var holo = Vacio(m.transform, "Holograma", new Vector3(0, 0.95f, -0.4f));
        var hm = AditivoPlano("Holo_Verde", new Color(0.25f, 1f, 0.6f, 0.22f));
        for (int i = 0; i < 7; i++)
        {
            var u = Box(holo.transform, "Unidad" + i, new Vector3(-1.5f + (i * 0.53f), 0.18f + (i % 3) * 0.12f, -0.8f + (i * 37 % 16) / 10f), new Vector3(0.12f, 0.12f, 0.12f), i % 3 == 0 ? mHoloRosa : hm, new Vector3(45, 45, 0));
            var ug = u.AddComponent<BRTVGiro>(); ug.vel = 40; ug.flota = 0.04f; ug.flotaVel = 1 + i * 0.2f;
        }
        MeshGO(holo.transform, "Radar", toroFino, new Vector3(0, 0.02f, 0), Vector3.one * 1.1f, nVerde).AddComponent<BRTVGiro>().vel = 25;
        Persona(m.transform, "Analista", new Vector3(5.6f, 0, -2.4f), 230, BRTVDoll.Modo.Holomesa, 1.68f);
        Puesto(m.transform, "PuestoAnalista", new Vector3(5.2f, 0, 1.8f), 260, 1, true);
        Foco(m.transform, "Llave", new Vector3(0, 6.5f, 4.0f), new Vector3(0, 1.3f, -1.7f), new Color(0.9f, 1f, 0.95f), 3f, false, true, 36);
        Foco(m.transform, "Mesa", new Vector3(0, 6.6f, -0.4f), new Vector3(0, 0.9f, -0.4f), GREEN, 2f, false, false, 40);
        Foco(m.transform, "Contra", new Vector3(-3.5f, 6.6f, -5f), new Vector3(-1, 1.2f, -1.7f), new Color(0.3f, 0.6f, 1f), 4.5f, true);
        Luz(m.transform, "Pantallas", LightType.Point, new Vector3(0, 2.8f, -5.2f), Vector3.zero, GREEN, 1.4f, 6);
        CamaraEstudio(m.transform, "CamEstudio1", new Vector3(2.8f, 0, 4.8f), new Vector3(-0.5f, 0, -0.5f), false);

        Vector3 mj = new Vector3(7.5f - 1.1f, 0, -2.05f), mk = new Vector3(7.5f + 1.1f, 0, -2.05f);
        var s2 = Set(sala, "militar", "ANÁLISIS MILITAR", false, 0.5f, mj, 8, mk, -8);
        Plano(s2, "amplio", new Vector3(7.5f, 2.6f, 7.6f), new Vector3(7.5f, 1.4f, -2.5f), 46);
        Plano(s2, "dos", new Vector3(7.5f, 1.7f, 3.4f), new Vector3(7.5f, 1.3f, -1.8f), 40);
        Plano(s2, "joy", new Vector3(7.1f, 1.55f, 1.0f), mj + new Vector3(0, 1.4f, 0), 30, "joy", 0.08f);
        Plano(s2, "kuroki", new Vector3(7.9f, 1.55f, 1.0f), mk + new Vector3(0, 1.4f, 0), 30, "kuroki", 0.08f);
        Plano(s2, "mesa", new Vector3(9.8f, 3.1f, 1.6f), new Vector3(7.5f, 0.9f, -0.4f), 44, "", 0.2f);
    }

    // -------------------------------------------------------------------------------------------- SALA DE PRENSA (D.T.)
    static void Prensa(Transform raiz, float x)
    {
        var sala = Sala(raiz, "SALA_DE_PRENSA", x, 22, 7, 13); var t = sala.transform;
        // muro de auspiciadores (marcas ficticias 2049)
        var muro = Vacio(t, "MuroMarcas", new Vector3(0, 0, -4.2f));
        Box(muro.transform, "Panel", new Vector3(0, 1.9f, -0.05f), new Vector3(10, 3.8f, 0.1f), Std("Panel_Prensa", "#B9AEC2", 0.05f, 0.35f));
        string[] marcas = { "<color=#FF4FB8>BLACKROSE</color> TV", "BIMBOLAND", "MAGLEV <color=#4BE3FF>2049</color>", "ROSE ENERGY", "CHROME HEELS", "NEO SANTIAGO FC", "ORBITAL BANK", "KUROKI LABS" };
        int k = 0;
        for (int fy = 0; fy < 5; fy++)
            for (int fx = 0; fx < 5; fx++)
            {
                float px = -4f + fx * 2f + (fy % 2) * 1.0f - 0.5f; if (px > 4.6f) continue;
                Texto(muro.transform, "Marca" + k, new Vector3(px, 0.5f + fy * 0.72f, 0.01f), marcas[k % marcas.Length], 1.3f, (k % 3 == 0) ? Hex("#160A1A") : Hex("#7A1033"), 2);
                k++;
            }
        Box(muro.transform, "MarcoNeon", new Vector3(0, 3.83f, 0), new Vector3(10, 0.04f, 0.04f), nRosa);
        // mesa con mantel y micrófonos
        var mesa = Vacio(t, "Mesa", new Vector3(0, 0, -1.9f));
        Box(mesa.transform, "Tablero", new Vector3(0, 0.74f, 0), new Vector3(4.2f, 0.05f, 0.9f), mNegro);
        Box(mesa.transform, "Faldon", new Vector3(0, 0.38f, 0.44f), new Vector3(4.2f, 0.76f, 0.02f), mMantel);
        Box(mesa.transform, "FaldonNeon", new Vector3(0, 0.1f, 0.46f), new Vector3(4.2f, 0.02f, 0.01f), nRosa);
        Texto(mesa.transform, "Logo", new Vector3(0, 0.45f, 0.46f), "CONFERENCIA DE PRENSA · <color=#FF4FB8>BRTV</color>", 1.8f, WHITE, 4);
        string[] dts = { "D.T. JOY", "D.T. KUROKI" };
        for (int a = 0; a < 2; a++)
        {
            float sx = a == 0 ? -0.8f : 0.8f;
            Box(mesa.transform, "Placa" + a, new Vector3(sx, 0.86f, 0.32f), new Vector3(0.5f, 0.14f, 0.02f), mNegro, new Vector3(-15, 0, 0));
            Texto(mesa.transform, "PlacaTxt" + a, new Vector3(sx, 0.86f, 0.333f), dts[a], 0.9f, WHITE, 0.5f, new Vector3(-15, 180, 0));
            Cyl(mesa.transform, "Botella" + a, new Vector3(sx + 0.42f, 0.88f, 0.05f), new Vector3(0.07f, 0.1f, 0.07f), mVidrio);
            for (int i = 0; i < 6; i++)
            {   // racimo de micrófonos con cubos de colores (medios)
                float mx = sx + (i - 2.5f) * 0.09f; var mic = Vacio(mesa.transform, $"Mic{a}{i}", new Vector3(mx, 0.79f, 0.18f + (i % 2) * 0.05f), new Vector3(-28 + (i % 3) * 6, (i - 2.5f) * 7, 0));
                Cyl(mic.transform, "Vara", new Vector3(0, 0.14f, 0), new Vector3(0.015f, 0.14f, 0.015f), mNegro);
                Esf(mic.transform, "Capsula", new Vector3(0, 0.3f, 0), 0.05f, mNegro);
                Box(mic.transform, "Cubo", new Vector3(0, 0.21f, 0), new Vector3(0.06f, 0.06f, 0.06f), new[] { mRosa, mCian, mPerla, mLavanda, mOro, nRojo }[(i + a * 2) % 6]);
            }
        }
        Vector3 pj = new Vector3(-0.8f, 0, -2.75f), pk = new Vector3(0.8f, 0, -2.75f);
        Silla(t, "SillaJ", pj + new Vector3(0, 0, -0.05f), 0, mNegro, 0.58f, false);
        Silla(t, "SillaK", pk + new Vector3(0, 0, -0.05f), 0, mNegro, 0.58f, false);
        // sillas de la prensa y periodistas
        for (int f = 0; f < 3; f++)
            for (int c = 0; c < 7; c++)
            {
                if (c == 3) continue;   // pasillo
                Silla(t, $"Prensa{f}{c}", new Vector3(-4.2f + c * 1.4f, 0, 2.2f + f * 1.4f), 180, mVelvet, 0.46f);
            }
        Persona(t, "Periodista1", new Vector3(-4.2f + 1.4f, 0, 2.2f), 180, BRTVDoll.Modo.Parada, 1.62f);
        Persona(t, "Periodista2", new Vector3(-4.2f + 5 * 1.4f, 0, 3.6f), 185, BRTVDoll.Modo.Parada, 1.7f);
        CamaraEstudio(t, "Tripode1", new Vector3(-3.5f, 0, 6.8f), new Vector3(0, 0, -2), true);
        CamaraEstudio(t, "Tripode2", new Vector3(0.0f, 0, 7.2f), new Vector3(0, 0, -2), false);
        CamaraEstudio(t, "Tripode3", new Vector3(3.5f, 0, 6.8f), new Vector3(0, 0, -2), true);
        Foco(t, "Llave", new Vector3(0, 6.4f, 3.5f), new Vector3(0, 1.3f, -2.6f), new Color(1f, 0.97f, 0.94f), 2.0f, false, true, 24);
        Foco(t, "Muro", new Vector3(0, 6.6f, 0.5f), new Vector3(0, 2, -4.2f), new Color(1f, 0.85f, 0.95f), 0.9f, false, false, 60);
        Luz(t, "Prensa1", LightType.Point, new Vector3(-2.5f, 4, 3.5f), Vector3.zero, new Color(0.9f, 0.7f, 1f), 2f, 8);
        Luz(t, "Prensa2", LightType.Point, new Vector3(2.5f, 4, 3.5f), Vector3.zero, new Color(0.9f, 0.7f, 1f), 2f, 8);
        Foco(t, "ContraR", new Vector3(-4f, 6.6f, -3.5f), new Vector3(-1, 1, -2.6f), PINK, 4f, true);

        var s = Set(sala, "prensa", "SALA DE PRENSA", true, 0.58f, pj, 0, pk, 0);
        Plano(s, "amplio", new Vector3(0, 2.3f, 9.0f), new Vector3(0, 1.3f, -2.5f), 40);
        Plano(s, "dos", new Vector3(0, 1.4f, 2.0f), new Vector3(0, 1.25f, -2.75f), 42);
        Plano(s, "joy", new Vector3(-0.35f, 1.4f, 0.4f), pj + new Vector3(0, 1.22f, 0), 30, "joy", 0.06f);
        Plano(s, "kuroki", new Vector3(0.35f, 1.4f, 0.4f), pk + new Vector3(0, 1.22f, 0), 30, "kuroki", 0.06f);
        Plano(s, "prensa", new Vector3(-6.5f, 2.2f, -1.0f), new Vector3(0, 1.0f, 3), 50, "", 0.2f);
    }

    // -------------------------------------------------------------------------------------------- PROGRAMA ESTELAR (noche en vivo)
    static void Estelar(Transform raiz, float x)
    {
        var sala = Sala(raiz, "ESTELAR", x, 32, 9, 16, 10f); var t = sala.transform;
        // escenario
        Box(t, "Escenario", new Vector3(0, 0.3f, -4.5f), new Vector3(16, 0.6f, 8), mNegro);
        Box(t, "EscenarioPiso", new Vector3(0, 0.605f, -4.5f), new Vector3(15.8f, 0.01f, 7.8f), mPisoSet);
        Box(t, "BordeNeon", new Vector3(0, 0.55f, -0.48f), new Vector3(16, 0.05f, 0.04f), nOro);
        for (int i = 0; i < 3; i++) Box(t, "Escalon" + i, new Vector3(0, 0.1f * (i + 1), -0.5f + (3 - i) * 0.35f - 0.175f), new Vector3(3.5f, 0.2f * (i + 1), 0.35f), mNegro);
        // telón de fondo: skyline 2049 en pantalla gigante
        Box(t, "MarcoFondo", new Vector3(0, 4.4f, -8.7f), new Vector3(15, 7.2f, 0.2f), mNegro);
        Quad(t, "Pantalla_Medio_Estelar", new Vector3(0, 4.4f, -8.55f), new Vector2(14.6f, 6.9f), tvSynth);
        Texto(t, "Marquesina", new Vector3(0, 8.6f, -8.4f), "<color=#FFC861>NOCHE ESTELAR</color> · BLACKROSE", 7f, WHITE, 18);
        // arco de bombillas (proscenio) en una sola malla
        var arco = Vacio(t, "ArcoBombillas", new Vector3(0, 0, -7.6f));
        var comb = new List<CombineInstance>(); var esf = Resources.GetBuiltinResource<Mesh>("New-Sphere.fbx");
        void Bomb(Vector3 p) => comb.Add(new CombineInstance { mesh = esf, transform = Matrix4x4.TRS(p, Quaternion.identity, Vector3.one * 0.13f) });
        float W = 13f, H = 7.6f;
        for (float yy = 0.8f; yy <= H; yy += 0.36f) { Bomb(new Vector3(-W / 2, yy, 0)); Bomb(new Vector3(W / 2, yy, 0)); Bomb(new Vector3(-W / 2 - 0.4f, yy + 0.18f, 0)); Bomb(new Vector3(W / 2 + 0.4f, yy + 0.18f, 0)); }
        for (float xx = -W / 2; xx <= W / 2; xx += 0.36f) { Bomb(new Vector3(xx, H, 0)); Bomb(new Vector3(xx + 0.18f, H + 0.4f, 0)); }
        var bm = new Mesh { name = "Bombillas", indexFormat = IndexFormat.UInt32 }; bm.CombineMeshes(comb.ToArray(), true, true); Guardar(bm, "Bombillas");
        MeshGO(arco.transform, "Bombillas", bm, Vector3.zero, Vector3.one, mFoco);
        Box(arco.transform, "ArcoI", new Vector3(-W / 2 - 0.2f, H / 2 + 0.4f, -0.1f), new Vector3(1.0f, H + 0.2f, 0.12f), mCromo);
        Box(arco.transform, "ArcoD", new Vector3(W / 2 + 0.2f, H / 2 + 0.4f, -0.1f), new Vector3(1.0f, H + 0.2f, 0.12f), mCromo);
        Box(arco.transform, "ArcoS", new Vector3(0, H + 0.2f, -0.1f), new Vector3(W + 1.4f, 0.9f, 0.12f), mCromo);
        // banda (izquierda): tarima, teclado, batería, atriles
        var banda = Vacio(t, "Banda", new Vector3(-5.2f, 0.6f, -5.6f));
        Box(banda.transform, "Tarima", new Vector3(0, 0.2f, 0), new Vector3(4, 0.4f, 3), mVelvet);
        Box(banda.transform, "TarimaNeon", new Vector3(0, 0.38f, 1.5f), new Vector3(4, 0.03f, 0.02f), nRosa);
        var bat = Vacio(banda.transform, "Bateria", new Vector3(0.5f, 0.4f, -0.4f));
        Cyl(bat.transform, "Bombo", new Vector3(0, 0.3f, 0.4f), new Vector3(0.55f, 0.2f, 0.55f), mRosa, new Vector3(90, 0, 0));
        Cyl(bat.transform, "Caja", new Vector3(-0.45f, 0.62f, 0.1f), new Vector3(0.35f, 0.08f, 0.35f), mCromo);
        Cyl(bat.transform, "Tom", new Vector3(0.1f, 0.78f, 0.25f), new Vector3(0.28f, 0.1f, 0.28f), mRosa, new Vector3(20, 0, 0));
        Cyl(bat.transform, "Platillo", new Vector3(0.6f, 1.15f, 0.2f), new Vector3(0.45f, 0.005f, 0.45f), mOro, new Vector3(-12, 0, 0));
        Cyl(bat.transform, "Hihat", new Vector3(-0.75f, 0.95f, 0.1f), new Vector3(0.35f, 0.005f, 0.35f), mOro);
        Box(banda.transform, "Teclado", new Vector3(-1.2f, 1.25f, 0.4f), new Vector3(1.2f, 0.06f, 0.35f), mNegro, new Vector3(0, 20, 0));
        Box(banda.transform, "TecladoLuz", new Vector3(-1.2f, 1.285f, 0.4f), new Vector3(1.1f, 0.005f, 0.2f), nBlanco, new Vector3(0, 20, 0));
        Cyl(banda.transform, "TecladoPie", new Vector3(-1.2f, 0.8f, 0.4f), new Vector3(0.05f, 0.42f, 0.05f), mCromo);
        Persona(banda.transform, "Tecladista", new Vector3(-1.45f, 0.4f, -0.2f), 20, BRTVDoll.Modo.Camarografa, 1.66f);
        // pie de micrófono central
        Cyl(t, "PieMic", new Vector3(0.6f, 1.35f, -1.6f), new Vector3(0.03f, 0.75f, 0.03f), mCromo);
        Esf(t, "Mic", new Vector3(0.6f, 2.15f, -1.6f), 0.07f, mNegro);
        // graderías vacías (el público son las avatares conectadas)
        for (int f = 0; f < 6; f++)
        {
            float gh = 0.5f + f * 0.5f;
            Box(t, "Grada" + f, new Vector3(0, gh * 0.5f, 5f + f * 1.2f), new Vector3(22, gh, 1.2f), mNegro);
            Box(t, "GradaNeon" + f, new Vector3(0, 0.5f + f * 0.5f + 0.01f, 4.41f + f * 1.2f), new Vector3(22, 0.02f, 0.02f), f % 2 == 0 ? nRosa : nViol);
            for (int c = 0; c < 14; c++)
            {
                if (c == 7) continue;
                float cx = -9.75f + c * 1.5f;
                Box(t, $"Butaca{f}_{c}", new Vector3(cx, 0.5f + f * 0.5f + 0.22f, 5.1f + f * 1.2f), new Vector3(0.55f, 0.12f, 0.5f), mVelvet);
                Box(t, $"Resp{f}_{c}", new Vector3(cx, 0.5f + f * 0.5f + 0.55f, 5.4f + f * 1.2f), new Vector3(0.55f, 0.6f, 0.08f), mVelvet);
            }
        }
        // focos de escenario con haces
        Foco(t, "Seguidor", new Vector3(0, 9.3f, 10f), new Vector3(0, 1.8f, -2f), new Color(1f, 0.95f, 0.9f), 3.5f, true, true, 20);
        Luz(t, "Grada1", LightType.Point, new Vector3(-6, 5, 8), Vector3.zero, VIOL, 2.5f, 10);
        Luz(t, "Grada2", LightType.Point, new Vector3(6, 5, 8), Vector3.zero, PINK, 2.5f, 10);
        for (int i = 0; i < 6; i++)
        {
            float fx = -6.5f + i * 2.6f; var c = i % 3 == 0 ? PINK : (i % 3 == 1 ? CYAN : VIOL);
            Foco(t, "Escena" + i, new Vector3(fx, 9.2f, -2.5f), new Vector3(fx * 0.4f, 0.6f, -4f + (i % 2) * 2), c, 4.5f, true, false, 28);
        }
        Luz(t, "Arco", LightType.Point, new Vector3(0, 4, -6.5f), Vector3.zero, new Color(1f, 0.8f, 0.55f), 2.5f, 10);
        CamaraEstudio(t, "CamEstudio1", new Vector3(-4.5f, 0, 2.5f), new Vector3(0, 0, -4), true);
        CamaraEstudio(t, "CamEstudio2", new Vector3(4.5f, 0, 2.5f), new Vector3(0, 0, -4), true);
        Persona(t, "Regidora", new Vector3(7.2f, 0, 1.2f), 230, BRTVDoll.Modo.Parada, 1.64f);

        var s = Set(sala, "estelar", "NOCHE ESTELAR", false, 0.5f, new Vector3(-0.7f, 0.6f, -1.6f), 6, new Vector3(1.0f, 0.6f, -1.9f), -10);
        Plano(s, "amplio", new Vector3(0, 4.4f, 12.0f), new Vector3(0, 3.0f, -5), 48, "", 0.5f);
        Plano(s, "escenario", new Vector3(0, 1.9f, 5.2f), new Vector3(0, 1.8f, -3), 42);
        Plano(s, "joy", new Vector3(-0.2f, 1.9f, 1.2f), new Vector3(-0.7f, 2.0f, -1.6f), 30, "joy", 0.1f);
        Plano(s, "kuroki", new Vector3(0.6f, 1.9f, 1.2f), new Vector3(1.0f, 2.0f, -1.9f), 30, "kuroki", 0.1f);
        Plano(s, "banda", new Vector3(-1.5f, 2.2f, 1.5f), new Vector3(-5.2f, 1.6f, -5.6f), 40, "", 0.2f);
        Plano(s, "grada", new Vector3(5.5f, 1.6f, -2.0f), new Vector3(-3f, 2.0f, 7), 56, "", 0.3f);
    }

    // -------------------------------------------------------------------------------------------- ciudad 2049 tras el ventanal
    static void Ciudad(Transform raiz)
    {
        var c = Vacio(raiz, "CIUDAD_2049", new Vector3(0, 0, -25));
        var r = new System.Random(2049);
        var comb = new List<CombineInstance>(); var antenas = new List<CombineInstance>();
        var cubo = CuboUV();
        for (int i = 0; i < 70; i++)
        {
            float x = (float)(r.NextDouble() * 360 - 180), z = -(float)(40 + r.NextDouble() * 220);
            float w = 8 + (float)r.NextDouble() * 18, d = 8 + (float)r.NextDouble() * 18, h = 25 + (float)(r.NextDouble() * r.NextDouble()) * 180;
            comb.Add(new CombineInstance { mesh = cubo, transform = Matrix4x4.TRS(new Vector3(x, h / 2 - 20, z), Quaternion.Euler(0, (float)r.NextDouble() * 20 - 10, 0), new Vector3(w, h, d)) });
            if (r.NextDouble() < 0.5) antenas.Add(new CombineInstance { mesh = Resources.GetBuiltinResource<Mesh>("Cube.fbx"), transform = Matrix4x4.TRS(new Vector3(x, h - 20 + 4, z), Quaternion.identity, new Vector3(0.5f, 8, 0.5f)) });
        }
        var m = new Mesh { name = "Ciudad", indexFormat = IndexFormat.UInt32 }; m.CombineMeshes(comb.ToArray(), true, true); Guardar(m, "Ciudad");
        var go = MeshGO(c.transform, "Edificios", m, Vector3.zero, Vector3.one, mCiudad); go.GetComponent<Renderer>().shadowCastingMode = ShadowCastingMode.Off;
        var ma = new Mesh { name = "Antenas" }; ma.CombineMeshes(antenas.ToArray(), true, true); Guardar(ma, "Antenas");
        MeshGO(c.transform, "Antenas", ma, Vector3.zero, Vector3.one, mCiudadGlow);
        // carteles holográficos en la ciudad
        Quad(c.transform, "Cartel1", new Vector3(-30, 40, -70), new Vector2(24, 13.5f), tvBimbo, new Vector3(0, 170, 0));
        Quad(c.transform, "Cartel2", new Vector3(45, 55, -120), new Vector2(30, 17), tvIdent, new Vector3(0, 195, 0));
        Quad(c.transform, "Cartel3", new Vector3(5, 30, -45), new Vector2(14, 8), tvSynth, new Vector3(0, 180, 0));
    }

    // cubo cuyas UV miden en metros/4 al escalarse por la matriz → el patrón de ventanas no se estira (UV por cara 0..1 → se escala en el shader con tiling)
    static Mesh CuboUV()
    {
        var src = Resources.GetBuiltinResource<Mesh>("Cube.fbx"); var m = Object.Instantiate(src);
        // UV de 0..1 por cara: subimos el tiling en el material
        mCiudad.mainTextureScale = new Vector2(6, 10); mCiudad.SetTextureScale("_EmissionMap", new Vector2(6, 10));
        return m;
    }

    // ============================================================================================ compilar
    public static bool Compilar()
    {
        // shaders que UniVRM necesita al cargar VRM en tiempo de ejecución + los de la API de medios
        var gs = AssetDatabase.LoadAssetAtPath<Object>("ProjectSettings/GraphicsSettings.asset");
        var so = new SerializedObject(gs); var arr = so.FindProperty("m_AlwaysIncludedShaders");
        for (int i = arr.arraySize - 1; i >= 0; i--)     // Standard acá = 65 000 variantes: lo traen los materiales de la escena
        { var o = arr.GetArrayElementAtIndex(i).objectReferenceValue as Shader; if (o != null && (o.name == "Standard" || o.name.StartsWith("Legacy Shaders/Particles"))) arr.DeleteArrayElementAtIndex(i); }
        foreach (var n in new[] { "VRM/MToon", "UniGLTF/UniUnlit", "Hidden/UniGLTF/StandardMapImporter", "Hidden/UniGLTF/NormalMapExporter", "Unlit/Texture" })
        {
            var sh = Shader.Find(n); if (sh == null) { Debug.LogWarning("[BRTV] falta shader " + n); continue; }
            bool ya = false; for (int i = 0; i < arr.arraySize; i++) if (arr.GetArrayElementAtIndex(i).objectReferenceValue == sh) ya = true;
            if (!ya) { arr.InsertArrayElementAtIndex(arr.arraySize); arr.GetArrayElementAtIndex(arr.arraySize - 1).objectReferenceValue = sh; }
        }
        so.ApplyModifiedProperties();
        PlayerSettings.productName = "BlackRose TV 2049"; PlayerSettings.companyName = "BlackRose";
        PlayerSettings.colorSpace = ColorSpace.Linear;
        PlayerSettings.defaultScreenWidth = 1920; PlayerSettings.defaultScreenHeight = 1080;
        PlayerSettings.fullScreenMode = FullScreenMode.Windowed; PlayerSettings.resizableWindow = true;
        PlayerSettings.runInBackground = true; PlayerSettings.visibleInBackground = true;
        PlayerSettings.SetApiCompatibilityLevel(BuildTargetGroup.Standalone, ApiCompatibilityLevel.NET_Unity_4_8);
        QualitySettings.shadowDistance = 45; QualitySettings.shadows = ShadowQuality.All; QualitySettings.shadowResolution = ShadowResolution.High;
        Directory.CreateDirectory(BuildDir);
        var r = BuildPipeline.BuildPlayer(new BuildPlayerOptions
        {
            scenes = new[] { EscenaPath }, locationPathName = BuildDir + "/BlackroseTV.x86_64", target = BuildTarget.StandaloneLinux64, options = BuildOptions.None
        });
        Debug.Log("[BRTV] build: " + r.summary.result + " " + r.summary.totalSize / 1048576 + " MB, errores " + r.summary.totalErrors);
        return r.summary.result == UnityEditor.Build.Reporting.BuildResult.Succeeded;
    }
}
