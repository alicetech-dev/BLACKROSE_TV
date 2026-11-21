using TMPro;
using UnityEngine;

// Letrero que va rotando frases (zócalo de titulares, carteles de la redacción). Fundido corto entre frase y frase.
public class BRTVRotador : MonoBehaviour
{
    public string[] items = { "BLACKROSE TV" };
    public float cada = 6;
    TextMeshPro t; int i; float prox, fase;
    void Start() { t = GetComponent<TextMeshPro>(); fase = Random.value * cada; prox = Time.time + fase; if (t && items.Length > 0) t.text = items[0]; }
    public void Poner(string[] l) { if (l == null || l.Length == 0) return; items = l; i = 0; prox = Time.time; }
    void Update()
    {
        if (!t || items.Length == 0) return;
        float d = prox - Time.time;
        t.alpha = Mathf.Clamp01(Mathf.Min(d, cada - d) * 3);
        if (d <= 0) { i = (i + 1) % items.Length; t.text = items[i]; prox = Time.time + cada; }
    }
}
