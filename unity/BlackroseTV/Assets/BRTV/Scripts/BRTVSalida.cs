// Salida al aire del estudio: la cámara rinde a una RenderTexture, AsyncGPUReadback la baja sin frenar el cuadro y un hilo
// la escribe cruda al stdin de ffmpeg, que la codifica (VAAPI de la AMD por defecto, para no tocar la RTX) y la manda por
// UDP/MPEG-TS a OBS (fuente multimedia «Estudio BRTV (Unity)»). Así corre en -batchmode, sin ventana ni captura de pantalla.
// Config brtv.json: "salida": {"url":"udp://127.0.0.1:9036?pkt_size=1316","ancho":1280,"alto":720,"voltear":true,"ffmpeg":"…args opcionales…"}
using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using Unity.Collections;
using UnityEngine;
using UnityEngine.Rendering;
using Debug = UnityEngine.Debug;

public class BRTVSalida : MonoBehaviour
{
    public Camera cam;
    public string url = "udp://127.0.0.1:9036?pkt_size=1316";
    public int ancho = 1280, alto = 720, fps = 30;
    public bool voltear = true;
    public string ffArgs;   // null = VAAPI AMD con respaldo libx264

    RenderTexture rtMsaa, rt;
    Process ff; Thread hilo; volatile bool vivo = true;
    readonly BlockingCollection<byte[]> cola = new BlockingCollection<byte[]>(3);
    readonly ConcurrentBag<byte[]> libres = new ConcurrentBag<byte[]>();
    int pedidos; float tLog; int enviados, tirados;
    bool usarX264;

    void Start()
    {
        rtMsaa = new RenderTexture(ancho, alto, 24, RenderTextureFormat.ARGB32) { antiAliasing = 4, name = "BRTV_aire_msaa" };
        rt = new RenderTexture(ancho, alto, 0, RenderTextureFormat.ARGB32) { name = "BRTV_aire" };
        cam.targetTexture = rtMsaa;
        hilo = new Thread(Escritor) { IsBackground = true, Name = "brtv-ffmpeg" }; hilo.Start();
        StartCoroutine(Bombear());
        Debug.Log($"[BRTV] salida {ancho}x{alto}@{fps} → {url}");
    }

    string Argumentos()
    {
        string entrada = $"-hide_banner -loglevel error -f rawvideo -pix_fmt rgba -s {ancho}x{alto} -use_wallclock_as_timestamps 1 -i - ";
        string vf = voltear ? "vflip," : "";
        string cod = !string.IsNullOrEmpty(ffArgs) ? ffArgs
            : !usarX264
                ? $"-vaapi_device /dev/dri/by-path/pci-0000:65:00.0-render -vf {vf}format=nv12,hwupload -fps_mode cfr -r {fps} -c:v h264_vaapi -qp 21 -g {fps} -bf 0 -bsf:v dump_extra=freq=keyframe"
                : $"-vf {vf}format=yuv420p -fps_mode cfr -r {fps} -c:v libx264 -preset ultrafast -tune zerolatency -crf 21 -g {fps} -x264-params repeat-headers=1";
        return entrada + cod + $" -flush_packets 1 -f mpegts \"{url}\"";
    }

    void Lanzar()
    {
        var psi = new ProcessStartInfo("ffmpeg", Argumentos()) { UseShellExecute = false, RedirectStandardInput = true, RedirectStandardError = true, CreateNoWindow = true };
        ff = Process.Start(psi);
        ff.ErrorDataReceived += (s, e) => { if (!string.IsNullOrEmpty(e.Data)) Debug.Log("[BRTV ffmpeg] " + e.Data); };
        ff.BeginErrorReadLine();
        Debug.Log("[BRTV] ffmpeg " + (usarX264 ? "libx264" : "vaapi") + " pid " + ff.Id);
    }

    void Escritor()
    {
        int fallos = 0;
        while (vivo)
        {
            try
            {
                if (ff == null || ff.HasExited)
                {
                    if (ff != null) { fallos++; if (fallos >= 2 && !usarX264 && string.IsNullOrEmpty(ffArgs)) { usarX264 = true; Debug.LogWarning("[BRTV] VAAPI falló, paso a libx264"); } Thread.Sleep(1000); }
                    Lanzar();
                }
                if (!cola.TryTake(out var b, 500)) continue;
                ff.StandardInput.BaseStream.Write(b, 0, b.Length);
                libres.Add(b); enviados++;
            }
            catch (Exception e) { Debug.LogWarning("[BRTV] salida: " + e.Message); try { ff?.Kill(); } catch { } ff = null; Thread.Sleep(1000); }
        }
    }

    IEnumerator Bombear()
    {
        var fin = new WaitForEndOfFrame();
        while (true)
        {
            yield return fin;
            if (pedidos > 2) { tirados++; continue; }   // la GPU va atrasada: no se apilan lecturas
            if (Application.isBatchMode) cam.Render();   // en -batchmode Unity no rinde las cámaras solo
            Graphics.Blit(rtMsaa, rt);
            pedidos++;
            AsyncGPUReadback.Request(rt, 0, TextureFormat.RGBA32, Listo);
            if (Time.unscaledTime - tLog > 60) { tLog = Time.unscaledTime; Debug.Log($"[BRTV] aire: {enviados} cuadros enviados, {tirados} tirados, {1f / Time.smoothDeltaTime:0} fps"); }
        }
    }

    void Listo(AsyncGPUReadbackRequest r)
    {
        pedidos--;
        if (r.hasError || !vivo) return;
        var datos = r.GetData<byte>();
        if (!libres.TryTake(out var b) || b.Length != datos.Length) b = new byte[datos.Length];
        datos.CopyTo(b);
        if (!cola.TryAdd(b)) { tirados++; libres.Add(b); }
    }

    void OnDestroy()
    {
        vivo = false;
        try { ff?.StandardInput.Close(); ff?.WaitForExit(1500); if (ff != null && !ff.HasExited) ff.Kill(); } catch { }
    }
}
