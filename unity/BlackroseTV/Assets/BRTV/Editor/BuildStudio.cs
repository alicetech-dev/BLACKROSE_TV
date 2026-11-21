// BlackRose TV Studio — arma la escena Studio.unity a partir de la estación (mismos 8 sets) y compila un build APARTE.
// El build del canal (BuildEstacion → ~/BlackroseTV_build) no se toca: Studio solo se compila con este menú.
//   Menú: BlackRose TV/Studio/Construir escena · BlackRose TV/Studio/Compilar Linux
//   Batch: Unity -batchmode -projectPath … -executeMethod BuildStudio.TodoBatch -quit
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.UIElements;

public static class BuildStudio
{
    const string Raiz = "Assets/BRTV";
    const string Estacion = Raiz + "/Scenes/Estacion.unity";
    const string Escena = Raiz + "/Scenes/Studio.unity";
    const string UI = Raiz + "/UI";
    static string BuildDir => Path.Combine(System.Environment.GetFolderPath(System.Environment.SpecialFolder.UserProfile), "BlackroseStudio_build");
    const string ConfigDef = "{\n  \"studio_url\": \"http://127.0.0.1:8840\",\n  \"fps\": 30,\n  \"texturas\": 0,\n  \"set\": \"noticiario\"\n}\n";

    [MenuItem("BlackRose TV/Studio/Construir escena")] public static void MenuEscena() { Construir(); }
    [MenuItem("BlackRose TV/Studio/Compilar Linux")] public static void MenuBuild() { if (!File.Exists(Escena)) Construir(); Compilar(); }

    public static void TodoBatch()
    {
        Construir();
        EditorApplication.Exit(Compilar() ? 0 : 1);
    }

    public static void Construir()
    {
        if (!File.Exists(Estacion)) BuildEstacion.Construir();
        var config = Path.Combine(Path.GetDirectoryName(Application.dataPath), "brtv_studio.json");   // la usa el modo Play del editor
        if (!File.Exists(config)) File.WriteAllText(config, ConfigDef);

        AssetDatabase.DeleteAsset(Escena);
        if (!AssetDatabase.CopyAsset(Estacion, Escena)) { Debug.LogError("[Studio] no pude copiar la estación"); return; }
        var escena = EditorSceneManager.OpenScene(Escena, OpenSceneMode.Single);

        var est = Object.FindObjectOfType<BRTVEstacion>(true);
        if (est == null) { Debug.LogError("[Studio] la escena no tiene BRTVEstacion"); return; }
        est.modoStudio = true;
        EditorUtility.SetDirty(est);
        LlenarPuestos();
        Equipo();

        var panel = AssetDatabase.LoadAssetAtPath<PanelSettings>(UI + "/StudioPanel.asset");
        if (panel == null)
        {
            panel = ScriptableObject.CreateInstance<PanelSettings>();
            AssetDatabase.CreateAsset(panel, UI + "/StudioPanel.asset");
        }
        panel.themeStyleSheet = AssetDatabase.LoadAssetAtPath<ThemeStyleSheet>(UI + "/StudioTema.tss");
        panel.scaleMode = PanelScaleMode.ScaleWithScreenSize;
        panel.referenceResolution = new Vector2Int(1920, 1080);
        panel.screenMatchMode = PanelScreenMatchMode.MatchWidthOrHeight; panel.match = 0.5f;
        EditorUtility.SetDirty(panel);

        var go = new GameObject("STUDIO");
        var doc = go.AddComponent<UIDocument>();
        doc.panelSettings = panel;
        doc.visualTreeAsset = AssetDatabase.LoadAssetAtPath<VisualTreeAsset>(UI + "/Studio.uxml");
        var st = go.AddComponent<BRTVStudio>(); st.estacion = est; st.ui = doc;

        EditorSceneManager.MarkSceneDirty(escena);
        EditorSceneManager.SaveScene(escena);
        AssetDatabase.SaveAssets();
        Debug.Log("[Studio] escena lista: " + Escena + (doc.visualTreeAsset == null ? " (¡falta Studio.uxml!)" : ""));
    }

    // Studio: en CADA puesto de trabajo (escritorio con silla) una periodista sentada tecleando; en el canal hay 2 de cada 3.
    // Sin tinte de pelo: el personal usa los VRM de "personal" en brtv_studio.json tal cual (p. ej. todas Kuroki).
    static void LlenarPuestos()
    {
        int n = 0, nuevas = 0;
        foreach (var t in Object.FindObjectsOfType<Transform>(true))
        {
            if (!t.name.StartsWith("Puesto") || t.Find("Silla") == null) continue;
            var d = t.GetComponentInChildren<BRTVDoll>(true);
            if (d == null)
            {
                var g = new GameObject("Periodista");
                g.transform.SetParent(t, false); g.transform.localPosition = new Vector3(0, 0, -0.1f);
                d = g.AddComponent<BRTVDoll>(); d.modo = BRTVDoll.Modo.Tecleando; d.altura = 1.64f; d.asiento = 0.5f; d.sentada = true;
                d.semilla = 500 + nuevas * 7.3f; d.id = "periodista" + nuevas; nuevas++;
            }
            d.tintePelo = new Color(0, 0, 0, 0);
            EditorUtility.SetDirty(d); n++;
        }
        Debug.Log($"[Studio] puestos con periodista: {n} ({nuevas} nuevas)");
    }

    // ============================================================ equipo del set (solo en Studio): todas son personal (VRM de "personal")
    static Material M(string n) => AssetDatabase.LoadAssetAtPath<Material>(Raiz + "/Materials/" + n + ".mat");
    static GameObject Caja(Transform p, string n, Vector3 lp, Vector3 tam, Material m, Vector3 rot = default)
    {
        var g = GameObject.CreatePrimitive(PrimitiveType.Cube); g.name = n; Object.DestroyImmediate(g.GetComponent<Collider>());
        g.transform.SetParent(p, false); g.transform.localPosition = lp; g.transform.localScale = tam; g.transform.localEulerAngles = rot;
        g.GetComponent<Renderer>().sharedMaterial = m; return g;
    }
    static GameObject Tubo(Transform p, string n, Vector3 lp, Vector3 tam, Material m, Vector3 rot = default)
    {
        var g = GameObject.CreatePrimitive(PrimitiveType.Cylinder); g.name = n; Object.DestroyImmediate(g.GetComponent<Collider>());
        g.transform.SetParent(p, false); g.transform.localPosition = lp; g.transform.localScale = tam; g.transform.localEulerAngles = rot;
        g.GetComponent<Renderer>().sharedMaterial = m; return g;
    }
    static GameObject Vacio(Transform p, string n, Vector3 lp, float yaw = 0)
    {
        var g = new GameObject(n); g.transform.SetParent(p, false); g.transform.localPosition = lp; g.transform.localEulerAngles = new Vector3(0, yaw, 0); return g;
    }
    static int nPersonas;
    static BRTVDoll Persona(Transform p, string n, Vector3 lp, float yaw, BRTVDoll.Modo modo, float asiento = 0.5f)
    {
        var d = Vacio(p, n, lp, yaw).AddComponent<BRTVDoll>();
        d.modo = modo; d.altura = 1.64f; d.asiento = asiento;
        d.sentada = modo == BRTVDoll.Modo.Tecleando || modo == BRTVDoll.Modo.Publico;
        d.tintePelo = new Color(0, 0, 0, 0); d.semilla = 900 + nPersonas * 3.7f; d.id = "equipo" + nPersonas++;
        return d;
    }
    static float Yaw(Vector3 desde, Vector3 hacia) { var d = hacia - desde; return Mathf.Atan2(d.x, d.z) * Mathf.Rad2Deg; }

    static void Equipo()
    {
        Material negro = M("Laca_Negra"), perla = M("Laca_Perla"), tapiz = M("Terciopelo_Blackrose"), rosa = M("Neon_Rosa"), cian = M("Neon_Cian"),
                 oro = M("Neon_Oro"), verde = M("Neon_Verde"), gris = M("Gris_Tactico"), cromo = M("Cromo"), eq = M("TV_EQ");
        int camaras = 0, publico = 0, salas = 0;
        foreach (var sala in Object.FindObjectsOfType<BRTVSet>(true).Select(x => x.transform.parent).Distinct().ToList())
        {
            var piso = sala.Find("Piso"); if (piso == null) continue;
            float ancho = piso.localScale.x, zMin = piso.localPosition.z - piso.localScale.z / 2, zMax = piso.localPosition.z + piso.localScale.z / 2;
            var eqp = Vacio(sala, "EQUIPO_STUDIO", Vector3.zero).transform; salas++;

            // camarógrafas en todas las cámaras de estudio
            foreach (var t in sala.GetComponentsInChildren<Transform>(true).ToList())
                if ((t.name.StartsWith("CamEstudio") || t.name.StartsWith("Tripode")) && t.Find("Visor") != null && t.GetComponentInChildren<BRTVDoll>(true) == null)
                { Persona(t, "Camarografa", new Vector3(0, 0, -0.75f), 0, BRTVDoll.Modo.Camarografa); camaras++; }

            // público: gradas a los dos costados, mirando al escenario (dos filas, la de atrás más alta)
            for (int lado = -1; lado <= 1; lado += 2)
            {
                float x0 = lado * Mathf.Min(5.3f, ancho / 2 - 3.2f), yaw = lado < 0 ? 90 : -90;   // cerca del escenario: entran en el plano amplio
                var grada = Vacio(eqp, lado < 0 ? "GradaIzq" : "GradaDer", Vector3.zero).transform;
                for (int fila = 0; fila < 2; fila++)
                {
                    float x = x0 + lado * fila * 1.05f, alto = fila * 0.42f;
                    if (alto > 0) Caja(grada, "Tarima" + fila, new Vector3(x, alto / 2, 2.6f), new Vector3(1.05f, alto, 5.6f), negro);
                    Caja(grada, "Banco" + fila, new Vector3(x + lado * 0.14f, alto + 0.42f, 2.6f), new Vector3(0.48f, 0.08f, 5.4f), tapiz);
                    Caja(grada, "BancoPata" + fila, new Vector3(x + lado * 0.14f, alto + 0.19f, 2.6f), new Vector3(0.4f, 0.38f, 5.2f), negro);
                    Caja(grada, "Neon" + fila, new Vector3(x - lado * 0.5f, alto + 0.02f, 2.6f), new Vector3(0.03f, 0.03f, 5.6f), fila == 0 ? rosa : cian);
                    for (int i = 0; i < 5; i++)
                    { Persona(grada, $"Publico_{fila}_{i}", new Vector3(x + lado * 0.04f, alto, 0.6f + i * 1.0f), yaw, BRTVDoll.Modo.Publico, 0.46f); publico++; }
                }

                var luz = new GameObject("LuzPublico").AddComponent<Light>(); luz.transform.SetParent(grada, false);
                luz.transform.localPosition = new Vector3(x0 + lado * 0.4f, 3.2f, 2.6f); luz.type = LightType.Point;
                luz.color = lado < 0 ? new Color(1f, 0.45f, 0.85f) : new Color(0.45f, 0.85f, 1f); luz.intensity = 4.5f; luz.range = 8.5f;
            }

            // sonido: consola de mezcla atrás de las cámaras + sonidista; microfonista con jirafa al costado de la mesa
            {
                var c = Vacio(eqp, "Sonido", new Vector3(ancho / 2 - 1.6f, 0, Mathf.Min(zMax - 1.6f, 8.5f)), -135).transform;
                Caja(c, "Cubierta", new Vector3(0, 0.74f, 0.45f), new Vector3(1.7f, 0.05f, 0.8f), perla);
                Caja(c, "Pata", new Vector3(0, 0.36f, 0.78f), new Vector3(1.6f, 0.72f, 0.08f), negro);
                Caja(c, "Mezcladora", new Vector3(0, 0.79f, 0.45f), new Vector3(1.4f, 0.05f, 0.55f), gris, new Vector3(-8, 0, 0));
                for (int i = 0; i < 12; i++)
                    Caja(c, "Fader" + i, new Vector3(-0.6f + i * 0.11f, 0.825f, 0.42f + (i % 3) * 0.05f), new Vector3(0.03f, 0.02f, 0.06f), i % 4 == 0 ? rosa : (i % 4 == 1 ? cian : (i % 4 == 2 ? verde : oro)));
                Caja(c, "Medidores", new Vector3(0, 1.12f, 0.8f), new Vector3(1.1f, 0.55f, 0.04f), eq);
                Caja(c, "Asiento", new Vector3(0, 0.45f, -0.15f), new Vector3(0.5f, 0.07f, 0.5f), negro);
                Persona(c, "Sonidista", new Vector3(0, 0, -0.1f), 0, BRTVDoll.Modo.Tecleando);

                var set = sala.GetComponentInChildren<BRTVSet>(true);
                var foco = set.puestoJoy ? set.puestoJoy.position : sala.position;
                var pm = sala.InverseTransformPoint(foco) + new Vector3(-2.6f, 0, 2.6f); pm.y = 0;
                var mic = Persona(eqp, "Microfonista", pm, Yaw(pm, sala.InverseTransformPoint(foco)), BRTVDoll.Modo.Camarografa).transform;
                var jirafa = Vacio(mic, "Jirafa", new Vector3(0, 1.7f, 0.3f)).transform; jirafa.localEulerAngles = new Vector3(-28, 0, 0);
                Tubo(jirafa, "Vara", new Vector3(0, 0, 1.1f), new Vector3(0.025f, 1.2f, 0.025f), cromo, new Vector3(90, 0, 0));
                Tubo(jirafa, "Micro", new Vector3(0, -0.08f, 2.3f), new Vector3(0.07f, 0.16f, 0.07f), gris, new Vector3(90, 0, 0));
                Caja(jirafa, "Peluche", new Vector3(0, -0.08f, 2.3f), new Vector3(0.11f, 0.11f, 0.3f), negro);
            }

            // tramoyas: al fondo, a los costados, con cajas de equipo y cable
            for (int lado = -1; lado <= 1; lado += 2)
            {
                var pt = new Vector3(lado * (ancho / 2 - 1.1f), 0, Mathf.Max(zMin + 2.2f, -4.5f) + (lado > 0 ? 1.2f : 0));
                var tr = Vacio(eqp, lado < 0 ? "TramoyaIzq" : "TramoyaDer", pt).transform;
                Caja(tr, "FlightCase", new Vector3(0.75f, 0.35f, 0.2f), new Vector3(0.6f, 0.7f, 0.5f), negro);
                Caja(tr, "FlightCaseNeon", new Vector3(0.75f, 0.69f, 0.2f), new Vector3(0.62f, 0.02f, 0.52f), oro);
                Caja(tr, "Caja2", new Vector3(0.75f, 0.85f, 0.2f), new Vector3(0.45f, 0.3f, 0.4f), gris);
                Tubo(tr, "RolloCable", new Vector3(-0.6f, 0.08f, 0.3f), new Vector3(0.55f, 0.08f, 0.55f), negro);
                Persona(tr, "Tramoya", Vector3.zero, Yaw(pt, new Vector3(0, 0, 0)), BRTVDoll.Modo.Parada);
            }

            // un plano nuevo por set para ver al público
            foreach (var set in sala.GetComponentsInChildren<BRTVSet>(true))
            {
                var g = new GameObject("Publico"); g.transform.SetParent(set.transform, false);
                float xg = Mathf.Min(5.3f, ancho / 2 - 3.2f);
                var desde = new Vector3(1.6f, 1.75f, 4.6f);
                g.transform.localPosition = desde;
                g.transform.localRotation = Quaternion.LookRotation(new Vector3(-xg - 0.5f, 0.85f, 2.4f) - desde);
                var pl = g.AddComponent<BRTVPlano>(); pl.fov = 52; pl.deriva = 0.3f;
                set.planos = set.planos.Concat(new[] { pl }).ToArray();
                EditorUtility.SetDirty(set);
            }
        }
        Debug.Log($"[Studio] equipo: {salas} salas · {camaras} camarógrafas nuevas · {publico} en el público · sonido, jirafa y tramoyas por sala");
    }

    public static bool Compilar()
    {
        // los mismos shaders que necesita UniVRM en tiempo de ejecución (BuildEstacion.Compilar ya los deja en GraphicsSettings)
        foreach (var n in new[] { "VRM/MToon", "UniGLTF/UniUnlit" })
            if (Shader.Find(n) == null) Debug.LogWarning("[Studio] falta shader " + n);
        var nombre = PlayerSettings.productName;
        PlayerSettings.productName = "BlackRose TV Studio";
        PlayerSettings.fullScreenMode = FullScreenMode.Windowed; PlayerSettings.resizableWindow = true;
        PlayerSettings.defaultScreenWidth = 1920; PlayerSettings.defaultScreenHeight = 1080;
        Directory.CreateDirectory(BuildDir);
        var r = UnityEditor.BuildPipeline.BuildPlayer(new BuildPlayerOptions
        {
            scenes = new[] { Escena }, locationPathName = Path.Combine(BuildDir, "BlackroseStudio.x86_64"),
            target = BuildTarget.StandaloneLinux64, options = BuildOptions.None,
        });
        PlayerSettings.productName = nombre;                 // el build del canal conserva su nombre
        var cfg = Path.Combine(BuildDir, "brtv_studio.json");
        if (!File.Exists(cfg)) File.WriteAllText(cfg, ConfigDef);
        Debug.Log("[Studio] build: " + r.summary.result + " " + r.summary.totalSize / 1048576 + " MB, errores " + r.summary.totalErrors);
        return r.summary.result == UnityEditor.Build.Reporting.BuildResult.Succeeded;
    }
}
