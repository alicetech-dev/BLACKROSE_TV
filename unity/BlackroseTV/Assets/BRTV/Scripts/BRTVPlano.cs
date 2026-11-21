using UnityEngine;

// Plano de cámara: posición/rotación del transform + fov. `foco` = "", "joy" o "kuroki" (primer plano de quien habla).
public class BRTVPlano : MonoBehaviour
{
    public float fov = 40;
    public string foco = "";
    public float deriva = 0.25f;     // movimiento lento de grúa (m)
}

