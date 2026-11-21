// Bimbo Mansion — material PBR triplanar en espacio mundo (built-in RP, lightmaps y probes).
// Para pisos y superficies de mármol sobre cajas con UV 0–1 por cara: la textura no se estira.
Shader "BRTV/TriplanarPBR"
{
    Properties
    {
        _Color     ("Tinte", Color) = (1,1,1,1)
        _MainTex   ("Albedo", 2D) = "white" {}
        _BumpMap   ("Normal", 2D) = "bump" {}
        _BumpScale ("Fuerza normal", Range(0,2)) = 0.6
        _SmoothTex ("Suavidad (R)", 2D) = "white" {}
        _Glossiness("Suavidad", Range(0,1)) = 0.85
        _Metallic  ("Metálico", Range(0,1)) = 0
        _Tile      ("Metros por repetición", Float) = 2.4
        _Sharp     ("Nitidez de la mezcla", Range(1,16)) = 8
        _CeilColor ("Color de caras hacia abajo (techos)", Color) = (0.97,0.94,0.95,1)
        _CeilSmooth("Suavidad de techos", Range(0,1)) = 0.3
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        LOD 300
        CGPROGRAM
        #pragma surface surf Standard fullforwardshadows vertex:vert
        #pragma target 3.0
        sampler2D _MainTex, _BumpMap, _SmoothTex;
        float _Tile, _Sharp, _Glossiness, _Metallic, _BumpScale;
        fixed4 _Color, _CeilColor; float _CeilSmooth;
        struct Input { float3 wpos; float3 wn; };

        void vert(inout appdata_full v, out Input o)
        {
            UNITY_INITIALIZE_OUTPUT(Input, o);
            o.wpos = mul(unity_ObjectToWorld, v.vertex).xyz;
            o.wn = UnityObjectToWorldNormal(v.normal);
        }

        void surf(Input IN, inout SurfaceOutputStandard o)
        {
            float3 n = normalize(IN.wn);
            float3 w = pow(abs(n), _Sharp); w /= (w.x + w.y + w.z);
            float2 uX = IN.wpos.zy / _Tile, uY = IN.wpos.xz / _Tile, uZ = IN.wpos.xy / _Tile;
            fixed3 c = tex2D(_MainTex, uX).rgb * w.x + tex2D(_MainTex, uY).rgb * w.y + tex2D(_MainTex, uZ).rgb * w.z;
            float s = tex2D(_SmoothTex, uX).r * w.x + tex2D(_SmoothTex, uY).r * w.y + tex2D(_SmoothTex, uZ).r * w.z;
            float2 dom = w.y >= w.x && w.y >= w.z ? uY : (w.x > w.z ? uX : uZ);
            o.Albedo = c * _Color.rgb;
            o.Normal = UnpackScaleNormal(tex2D(_BumpMap, dom), _BumpScale);
            o.Smoothness = saturate(s * _Glossiness);
            o.Metallic = _Metallic;
            // caras que miran hacia abajo = cielorraso: pintura lisa, sin mármol
            float isCeil = step(n.y, -0.5);
            o.Albedo = lerp(o.Albedo, _CeilColor.rgb, isCeil);
            o.Smoothness = lerp(o.Smoothness, _CeilSmooth, isCeil);
            o.Normal = lerp(o.Normal, float3(0, 0, 1), isCeil);
        }
        ENDCG
    }
    Fallback "Diffuse"
}
