// Un set de la estación: nombre (el que usa la API), sus planos de cámara y los puestos de las conductoras.
using UnityEngine;

public class BRTVSet : MonoBehaviour
{
    public string nombre = "noticiario";
    public string titulo = "NOTICIARIO";
    public bool sentadas = true;
    public float asiento = 0.48f;
    public Transform puestoJoy, puestoKuroki;
    public BRTVPlano[] planos;
}

