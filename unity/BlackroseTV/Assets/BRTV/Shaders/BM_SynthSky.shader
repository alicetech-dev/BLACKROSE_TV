// BIMBOLAND 2049 — cielo nocturno synthwave (skybox procedural, sin texturas):
// degradé violeta → negro, resplandor rosa en el horizonte, sol de franjas sobre el mar, estrellas y cuadrícula en la bóveda.
Shader "BRTV/SynthSky"
{
    Properties
    {
        [HDR] _Horizon ("Horizonte", Color) = (0.9, 0.15, 0.55, 1)
        _Mid ("Medio", Color) = (0.16, 0.04, 0.28, 1)
        _Top ("Cénit", Color) = (0.01, 0.005, 0.03, 1)
        _Below ("Bajo el horizonte", Color) = (0.02, 0.005, 0.04, 1)
        _SunDir ("Dirección del sol (mundo)", Vector) = (-0.55, 0.12, -0.8, 0)
        _SunSize ("Tamaño del sol (rad)", Float) = 0.16
        [HDR] _SunTop ("Sol arriba", Color) = (3, 2.2, 0.5, 1)
        [HDR] _SunBottom ("Sol abajo", Color) = (3.5, 0.4, 1.6, 1)
        [HDR] _GridColor ("Cuadrícula", Color) = (0.25, 0.6, 1.4, 1)
        _GridScale ("Escala cuadrícula", Float) = 3
        _StarDensity ("Estrellas", Range(0.98, 0.9999)) = 0.9975
        _Exposure ("Exposición", Float) = 1
    }
    SubShader
    {
        Tags { "Queue"="Background" "RenderType"="Background" "PreviewType"="Skybox" }
        Cull Off ZWrite Off
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            half4 _Horizon, _Mid, _Top, _Below, _SunTop, _SunBottom, _GridColor;
            float4 _SunDir; float _SunSize, _GridScale, _StarDensity, _Exposure;
            struct v2f { float4 pos : SV_POSITION; float3 dir : TEXCOORD0; };
            v2f vert (appdata_base v) { v2f o; o.pos = UnityObjectToClipPos(v.vertex); o.dir = v.vertex.xyz; return o; }
            float hash(float3 p) { p = frac(p * 0.3183099 + 0.1); p *= 17.0; return frac(p.x * p.y * p.z * (p.x + p.y + p.z)); }
            fixed4 frag (v2f i) : SV_Target
            {
                float3 d = normalize(i.dir); float y = d.y;
                float3 col;
                if (y < 0) col = lerp(_Horizon.rgb * 0.25, _Below.rgb, saturate(-y * 8));
                else
                {
                    float t = saturate(y);
                    col = lerp(_Horizon.rgb, _Mid.rgb, smoothstep(0.0, 0.18, t));
                    col = lerp(col, _Top.rgb, smoothstep(0.18, 0.75, t));
                    // estrellas
                    float3 sp = floor(d * 420);
                    float s = hash(sp);
                    col += step(_StarDensity, s) * smoothstep(0.04, 0.3, t) * (0.6 + 2.0 * frac(s * 91.7));
                    // cuadrícula de la bóveda (plano y = 1)
                    float2 g = d.xz / max(y, 0.02) * _GridScale;
                    float2 w = abs(frac(g) - 0.5); float2 fw = fwidth(g) * 1.5;
                    float2 l2 = 1 - smoothstep(fw, fw * 2, 0.5 - w);   // 0.5 − w = distancia a la línea
                    float line_ = max(l2.x, l2.y);
                    col += _GridColor.rgb * saturate(line_) * smoothstep(0.25, 0.7, t) * 0.35;
                }
                // sol de franjas
                float3 sd = normalize(_SunDir.xyz);
                float ang = acos(saturate(dot(d, sd)));
                if (ang < _SunSize && y > -0.01)
                {
                    float3 up = float3(0, 1, 0); float3 r = normalize(cross(up, sd)); float3 u = cross(sd, r);
                    float v = dot(d - sd, u) / _SunSize;        // −1 abajo .. 1 arriba
                    float3 sc = lerp(_SunBottom.rgb, _SunTop.rgb, saturate(v * 0.5 + 0.5));
                    float stripes = (v < 0.1) ? step(0.5 + v * 0.6, frac(v * 6)) : 1;
                    col = lerp(col, sc, stripes * smoothstep(_SunSize, _SunSize * 0.97, ang));
                }
                col += _SunBottom.rgb * 0.06 * exp(-ang * 4) ;  // halo
                return fixed4(col * _Exposure, 1);
            }
            ENDCG
        }
    }
    Fallback Off
}
