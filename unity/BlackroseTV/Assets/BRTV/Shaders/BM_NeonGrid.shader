// BIMBOLAND 2049 — superficie oscura brillante con cuadrícula/juntas emisivas en espacio de mundo.
//  · Pisos interiores: mármol negro con vetas (_VeinTex invertida) y juntas finas índigo.
//  · Exterior (M_SynthGrid): cuadrícula synthwave rosa con líneas mayores cian.
//  · Paredes: paneles (celda _Cell x _CellY) con juntas tenues.
// Paredes (caras verticales) y cielorrasos (caras hacia abajo) atenúan la emisión con _WallFactor / _CeilFactor.
// La emisión se hornea (Meta pass del surface shader).
Shader "BRTV/NeonGrid"
{
    Properties
    {
        _Color ("Base", Color) = (0.03, 0.02, 0.045, 1)
        _Glossiness ("Smoothness", Range(0,1)) = 0.92
        _Metallic ("Metallic", Range(0,1)) = 0.1
        [HDR] _GridColor ("Juntas / cuadrícula", Color) = (1, 0.18, 0.65, 1)
        [HDR] _MajorColor ("Líneas mayores", Color) = (0.25, 0.95, 1, 1)
        _Cell ("Celda (m)", Float) = 1
        _CellY ("Alto de panel en paredes (m)", Float) = 1
        _Major ("Celdas por línea mayor (0 = sin)", Float) = 4
        _Line ("Ancho de línea (m)", Float) = 0.025
        _Intensity ("Intensidad", Float) = 1.3
        _WallFactor ("Factor paredes", Range(0,1)) = 0.5
        _CeilFactor ("Factor cielorraso", Range(0,1)) = 0.3
        _VeinTex ("Vetas (mármol claro, se invierte)", 2D) = "white" {}
        _VeinColor ("Color de vetas", Color) = (0, 0, 0, 1)
        _VeinScale ("Escala vetas (m)", Float) = 2.5
        _VeinSharp ("Contraste vetas", Float) = 3
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        LOD 300
        CGPROGRAM
        #pragma surface surf Standard fullforwardshadows addshadow
        #pragma target 3.0
        // agujeros del Terrain (2026-11-09): sin esto el terreno se dibujaba a nivel del suelo sobre la piscina, la playa,
        // el mar costero y la marina aunque el collider sí tuviera el agujero. Unity activa _ALPHATEST_ON en terrenos con agujeros.
        #pragma multi_compile_local __ _ALPHATEST_ON
        sampler2D _TerrainHolesTexture;
        struct Input { float3 worldPos; float3 worldNormal; float2 uv_TerrainHolesTexture; };
        fixed4 _Color, _VeinColor; half _Glossiness, _Metallic;
        half4 _GridColor, _MajorColor;
        float _Cell, _CellY, _Major, _Line, _Intensity, _WallFactor, _CeilFactor, _VeinScale, _VeinSharp;
        sampler2D _VeinTex;

        float GridLine(float2 p, float2 cell, float w)
        {
            float2 d = abs(frac(p / cell - 0.5) - 0.5) * cell;     // distancia en metros a la línea más cercana
            float2 aa = fwidth(p) * 1.2;
            float2 l = 1 - smoothstep(w * 0.5, w * 0.5 + aa, d);
            return max(l.x, l.y);
        }

        void surf (Input IN, inout SurfaceOutputStandard o)
        {
            #if defined(_ALPHATEST_ON)
            clip(tex2D(_TerrainHolesTexture, IN.uv_TerrainHolesTexture).r == 0.0f ? -1 : 1);
            #endif
            float3 n = normalize(IN.worldNormal); float3 an = abs(n);
            float2 p; float f; float2 cell = _Cell.xx; bool floorFace = false;
            if (an.y >= an.x && an.y >= an.z) { p = IN.worldPos.xz; f = n.y > 0 ? 1 : _CeilFactor; floorFace = n.y > 0; }
            else if (an.x >= an.z) { p = IN.worldPos.zy; f = _WallFactor; cell = float2(_Cell, _CellY); }
            else { p = IN.worldPos.xy; f = _WallFactor; cell = float2(_Cell, _CellY); }
            float minor = GridLine(p, cell, _Line);
            float major = _Major > 0.5 ? GridLine(p, cell * _Major, _Line * 1.6) : 0;
            float3 glow = lerp(_GridColor.rgb * minor, _MajorColor.rgb, major);
            float3 alb = _Color.rgb;
            if (floorFace && _VeinColor.a > 0)
            {
                float3 t = tex2D(_VeinTex, p / _VeinScale).rgb;
                float v = saturate((1 - dot(t, float3(0.333, 0.333, 0.333))) * _VeinSharp - 0.15);
                alb = lerp(alb, _VeinColor.rgb, v * _VeinColor.a);
            }
            o.Albedo = alb * (1 - minor * 0.6);
            o.Metallic = _Metallic;
            o.Smoothness = _Glossiness * (1 - minor * 0.3);
            o.Emission = glow * _Intensity * f;
            o.Alpha = 1;
        }
        ENDCG
    }
    FallBack "Standard"
}
