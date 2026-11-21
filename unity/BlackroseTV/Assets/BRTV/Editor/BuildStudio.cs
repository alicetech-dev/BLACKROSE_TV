// BlackRose TV Studio — arma la escena Studio.unity a partir de la estación (mismos 8 sets) y compila un build APARTE.
// El build del canal (BuildEstacion → ~/BlackroseTV_build) no se toca: Studio solo se compila con este menú.
//   Menú: BlackRose TV/Studio/Construir escena · BlackRose TV/Studio/Compilar Linux
//   Batch: Unity -batchmode -projectPath … -executeMethod BuildStudio.TodoBatch -quit
using System.IO;
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
