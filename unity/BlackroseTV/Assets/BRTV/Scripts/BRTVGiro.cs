using UnityEngine;

public class BRTVGiro : MonoBehaviour
{
    public Vector3 eje = Vector3.up;
    public float vel = 20;
    public float flota = 0, flotaVel = 0.6f;
    Vector3 p0; float fase;
    void Start() { p0 = transform.localPosition; fase = Random.value * 10; }
    void Update()
    {
        transform.Rotate(eje, vel * Time.deltaTime, Space.Self);
        if (flota > 0) transform.localPosition = p0 + Vector3.up * Mathf.Sin((Time.time + fase) * flotaVel) * flota;
    }
}

