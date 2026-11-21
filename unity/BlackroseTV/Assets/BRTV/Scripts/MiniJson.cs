// Parser JSON mínimo (objetos → Dictionary<string,object>, arreglos → List<object>, números → double).
// JsonUtility no lee diccionarios y los cuadros VMC del overlay vienen como {"h":{"Hips":[x,y,z,w],...}}.
using System.Collections.Generic;
using System.Globalization;
using System.Text;

public static class MiniJson
{
    public static object Parse(string s) { int i = 0; try { return Val(s, ref i); } catch { return null; } }

    static void Ws(string s, ref int i) { while (i < s.Length && char.IsWhiteSpace(s[i])) i++; }

    static object Val(string s, ref int i)
    {
        Ws(s, ref i);
        char c = s[i];
        if (c == '{')
        {
            var d = new Dictionary<string, object>(); i++; Ws(s, ref i);
            if (s[i] == '}') { i++; return d; }
            while (true)
            {
                Ws(s, ref i); var k = Str(s, ref i); Ws(s, ref i); i++;   // ':'
                d[k] = Val(s, ref i); Ws(s, ref i);
                if (s[i] == ',') { i++; continue; }
                i++; return d;                                            // '}'
            }
        }
        if (c == '[')
        {
            var l = new List<object>(); i++; Ws(s, ref i);
            if (s[i] == ']') { i++; return l; }
            while (true)
            {
                l.Add(Val(s, ref i)); Ws(s, ref i);
                if (s[i] == ',') { i++; continue; }
                i++; return l;
            }
        }
        if (c == '"') return Str(s, ref i);
        if (s.Length - i >= 4 && s.Substring(i, 4) == "true") { i += 4; return true; }
        if (s.Length - i >= 5 && s.Substring(i, 5) == "false") { i += 5; return false; }
        if (s.Length - i >= 4 && s.Substring(i, 4) == "null") { i += 4; return null; }
        int a = i; while (i < s.Length && "+-0123456789.eE".IndexOf(s[i]) >= 0) i++;
        return double.Parse(s.Substring(a, i - a), CultureInfo.InvariantCulture);
    }

    static string Str(string s, ref int i)
    {
        var sb = new StringBuilder(); i++;
        while (s[i] != '"')
        {
            if (s[i] == '\\')
            {
                i++; char e = s[i];
                if (e == 'n') sb.Append('\n'); else if (e == 't') sb.Append('\t'); else if (e == 'r') { }
                else if (e == 'u') { sb.Append((char)int.Parse(s.Substring(i + 1, 4), NumberStyles.HexNumber)); i += 4; }
                else sb.Append(e);
            }
            else sb.Append(s[i]);
            i++;
        }
        i++; return sb.ToString();
    }

    public static string Esc(string s) => s == null ? "" : s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n");
}
