using UnityEngine;

// Luz que late suave (letreros AL AIRE, núcleo)
public class BRTVLatido : MonoBehaviour
{
    public float min = 0.6f, max = 1.4f, vel = 2;
    Light l; float b;
    void Start() { l = GetComponent<Light>(); if (l) b = l.intensity; }
    void Update() { if (l) l.intensity = b * Mathf.Lerp(min, max, 0.5f + 0.5f * Mathf.Sin(Time.time * vel)); }
}
