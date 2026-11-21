// Bimbo Mansion — pantallas encendidas (pedido 2026-11-09: "falta encender los televisores para poder ver algo").
// Contenido procedural animado, sin video (no pesa en el bundle y siempre funciona). Modos (_Mode):
//   0 = viaje synthwave (sol de franjas, montañas, cuadrícula que avanza)   — cine, cabañas, salones
//   1 = HUD de datos (barras que corren, onda, radar)                      — hacker, operaciones
//   2 = espiral rosa lenta                                                  — gooncave
//   3 = ecualizador                                                         — DJ
//   4 = BIMBO TV (corazón que late sobre franjas)                           — bar, playa
// uv del quad 0..1. _Seed desincroniza pantallas vecinas. Scanlines y viñeta tipo CRT.
Shader "BRTV/TVScreen"
{
    Properties
    {
        _Mode ("Modo", Float) = 0
        _Seed ("Semilla", Float) = 0
        _Bright ("Brillo", Float) = 1.6
        _Aspect ("Ancho / alto", Float) = 1.7778
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" "Queue"="Geometry" }
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #pragma multi_compile_instancing
            #include "UnityCG.cginc"
            float _Mode, _Seed, _Bright, _Aspect;
            struct appdata { float4 vertex : POSITION; float2 uv : TEXCOORD0; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct v2f { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; UNITY_FOG_COORDS(1) UNITY_VERTEX_OUTPUT_STEREO };
            v2f vert(appdata v) { v2f o; UNITY_SETUP_INSTANCE_ID(v); UNITY_INITIALIZE_OUTPUT(v2f, o); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = UnityObjectToClipPos(v.vertex); o.uv = v.uv; UNITY_TRANSFER_FOG(o, o.pos); return o; }
            float hash(float n) { return frac(sin(n) * 43758.5453); }
            static const float3 PINK = float3(1, 0.2, 0.7), CYAN = float3(0.2, 0.95, 1), VIOL = float3(0.45, 0.15, 0.9), GOLD = float3(1, 0.8, 0.25);

            float3 Synthwave(float2 uv, float t)
            {
                float2 p = float2((uv.x - 0.5) * _Aspect, uv.y - 0.42);
                float3 sky = lerp(float3(0.9, 0.2, 0.55), float3(0.08, 0.02, 0.18), saturate(p.y * 1.8));
                float3 col = sky;
                // sol de franjas
                float d = length(p - float2(0, 0.17));
                if (d < 0.26 && p.y > -0.0) {
                    float bands = step(0.5, frac((p.y - 0.17) * 14 + t * 0.4)) + step(0.05, p.y - 0.12);
                    col = lerp(GOLD, PINK, saturate(0.5 - p.y * 2.2)) * saturate(bands);
                    if (bands < 0.5) col = sky;
                }
                // montañas
                float m = 0.06 + 0.07 * abs(sin(p.x * 5.1 + 1.3)) + 0.04 * abs(sin(p.x * 13.7));
                if (p.y < m && p.y > 0) col = lerp(float3(0.05, 0.0, 0.1), VIOL * 0.6, saturate(1 - abs(frac(p.x * 6 + p.y * 9) - 0.5) * 8) * 0.6);
                // cuadrícula que avanza
                if (p.y <= 0) {
                    float z = 0.12 / max(-p.y, 0.002);
                    float gx = abs(frac(p.x * z * 1.3) - 0.5), gz = abs(frac(z - t * 1.8) - 0.5);
                    float g = saturate(1 - min(gx, gz) * 18 / (1 + z * 0.3));
                    col = float3(0.03, 0, 0.07) + PINK * g * saturate(1.5 - z * 0.08);
                }
                return col;
            }
            float3 HUD(float2 uv, float t)
            {
                float3 col = float3(0.0, 0.03, 0.06);
                float cols = 28;
                float c = floor(uv.x * cols);
                float spd = 0.2 + hash(c + _Seed) * 0.8;
                float y = frac(uv.y + t * spd * 0.3 + hash(c * 3.1));
                float cell = step(0.35, hash(floor(y * 22) + c * 17.0 + floor(t * spd * 2)));
                col += CYAN * cell * step(0.25, frac(uv.x * cols)) * step(frac(y * 22), 0.7) * 0.35 * step(uv.x, 0.55);
                // onda
                float w = 0.78 + 0.08 * sin(uv.x * 30 + t * 4) * sin(uv.x * 7 - t);
                col += PINK * saturate(1 - abs(uv.y - w) * 120) * step(0.58, uv.x);
                // radar
                float2 r = float2((uv.x - 0.79) * _Aspect, uv.y - 0.35);
                float rd = length(r); float ang = atan2(r.y, r.x);
                float sweep = frac((ang / 6.2832) - t * 0.25);
                col += CYAN * step(rd, 0.27) * (pow(sweep, 8) * 0.9 + step(abs(frac(rd * 12) - 0.5), 0.04) * 0.25);
                return col;
            }
            float3 Spiral(float2 uv, float t)
            {
                float2 p = float2((uv.x - 0.5) * _Aspect, uv.y - 0.5);
                float r = length(p), a = atan2(p.y, p.x);
                float s = sin(a * 2 + log(max(r, 0) + 0.02) * 9 - t * 1.2);
                return lerp(float3(0.05, 0, 0.08), PINK, smoothstep(-0.1, 0.1, s)) * (1.2 - r);
            }
            float3 EQ(float2 uv, float t)
            {
                float bars = 24; float b = floor(uv.x * bars);
                float h = 0.15 + 0.7 * saturate(0.5 + 0.5 * sin(t * (2 + hash(b) * 4) + b * 0.7) * sin(t * 1.3 + hash(b + 9) * 6));
                float on = step(uv.y, h) * step(0.15, frac(uv.x * bars)) * step(0.3, frac(uv.y * 30));
                float3 c = lerp(CYAN, PINK, uv.y * 1.3);
                return float3(0.02, 0, 0.05) + c * on;
            }
            float3 BimboTV(float2 uv, float t)
            {
                float2 p = float2((uv.x - 0.5) * _Aspect, uv.y - 0.5);
                float3 col = lerp(float3(0.25, 0.02, 0.2), float3(0.05, 0.1, 0.25), step(0.5, frac((p.x + p.y) * 4 + t * 0.2)));
                float beat = 1 + 0.12 * pow(abs(sin(t * 2.4)), 6);
                float2 q = p / (0.33 * beat); q.y -= 0.25;
                float hb = q.x * q.x + q.y * q.y - 0.3; float hrt = hb * hb * hb - q.x * q.x * q.y * q.y * q.y;   // sin pow(): pow de negativo = NaN   // corazón implícito
                col = lerp(col, PINK * 1.3, step(hrt, 0));
                col += CYAN * saturate(1 - abs(hrt) * 60) * 0.8;
                return col;
            }

            // ---- BlackRose TV 2049: 5 tiempo, 6 cancha, 7 táctico, 8 ident del canal
            float noise2(float2 p) { float2 i = floor(p), f = frac(p); f = f * f * (3 - 2 * f);
                float a = hash(dot(i, float2(1, 57))), b = hash(dot(i + float2(1, 0), float2(1, 57))), c = hash(dot(i + float2(0, 1), float2(1, 57))), d = hash(dot(i + float2(1, 1), float2(1, 57)));
                return lerp(lerp(a, b, f.x), lerp(c, d, f.x), f.y); }
            float fbm(float2 p) { float v = 0, a = 0.5; for (int k = 0; k < 4; k++) { v += a * noise2(p); p *= 2.03; a *= 0.5; } return v; }
            float3 Weather(float2 uv, float t)
            {
                float2 p = float2(uv.x * _Aspect, uv.y) * 3;
                float land = smoothstep(0.52, 0.55, fbm(p * 0.7 + 3.1));
                float temp = fbm(p * 0.35 + float2(t * 0.02, 0));
                float3 heat = lerp(float3(0.1, 0.35, 1), float3(1, 0.25, 0.55), saturate(temp * 1.6 - 0.3));
                float3 col = lerp(float3(0.02, 0.03, 0.12), heat * 0.55, land);
                col += CYAN * saturate(1 - abs(frac(temp * 14) - 0.5) * 30) * 0.35;                    // isobaras
                float cl = fbm(p * 1.3 + float2(t * 0.12, t * 0.03)); col = lerp(col, float3(0.95, 0.9, 1), smoothstep(0.55, 0.8, cl) * 0.7);
                float2 g = abs(frac(p * 2) - 0.5); col += VIOL * 0.25 * step(min(g.x, g.y), 0.012);
                return col;
            }
            float3 Pitch(float2 uv, float t)
            {
                float2 p = uv; float3 col = lerp(float3(0.02, 0.1, 0.08), float3(0.03, 0.16, 0.12), step(0.5, frac(p.x * 10)));
                float2 c = float2(abs(p.x - 0.5) * _Aspect, p.y - 0.5);
                float ln = step(abs(length(c) - 0.12), 0.004) + step(abs(p.x - 0.5), 0.002) + step(min(min(p.x, 1 - p.x), min(p.y, 1 - p.y)), 0.02) * step(0.012, min(min(p.x, 1 - p.x), min(p.y, 1 - p.y)) + 0.01);
                ln += step(abs(abs(p.x - 0.5) - 0.42), 0.002) * step(abs(p.y - 0.5), 0.2);
                col += float3(0.8, 1, 0.95) * saturate(ln) * 0.8;
                for (int k = 0; k < 10; k++) { float2 q = float2(0.15 + 0.7 * hash(k * 3.1), 0.15 + 0.7 * hash(k * 7.7)) + 0.08 * float2(sin(t * 0.7 + k), cos(t * 0.5 + k * 1.3));
                    float d = length((p - q) * float2(_Aspect, 1)); col += (k < 5 ? PINK : CYAN) * saturate(1 - d * 60) * 1.5; }
                float2 bq = float2(0.5 + 0.3 * sin(t * 0.9), 0.5 + 0.25 * sin(t * 1.3)); col += float3(1, 1, 1) * saturate(1 - length((p - bq) * float2(_Aspect, 1)) * 120) * 2;
                return col;
            }
            float3 Tactical(float2 uv, float t)
            {
                float2 p = float2((uv.x - 0.5) * _Aspect, uv.y - 0.5);
                float land = smoothstep(0.5, 0.52, fbm(p * 2.2 + 7.0));
                float3 col = lerp(float3(0.0, 0.03, 0.05), float3(0.02, 0.12, 0.1), land);
                col += float3(0.2, 1, 0.6) * saturate(1 - abs(frac(fbm(p * 2.2 + 7.0) * 10) - 0.5) * 25) * 0.25 * land;
                float2 g = abs(frac(p * 6) - 0.5); col += float3(0.1, 0.5, 0.4) * 0.3 * step(min(g.x, g.y), 0.015);
                float r = length(p), a = atan2(p.y, p.x); float sw = frac((a / 6.2832) - t * 0.15);
                col += float3(0.2, 1, 0.6) * pow(saturate(1 - sw), 12) * step(r, 0.45) * 0.7;
                col += float3(0.2, 1, 0.6) * step(abs(frac(r * 9) - 0.5), 0.02) * step(r, 0.45) * 0.4;
                for (int k = 0; k < 7; k++) { float2 q = float2(hash(k * 5.3) - 0.5, hash(k * 9.1) - 0.5) * 0.8; float d = length(p - q);
                    col += (k % 3 == 0 ? float3(1, 0.3, 0.3) : CYAN) * (saturate(1 - d * 90) + step(abs(d - 0.02 - 0.01 * sin(t * 3 + k)), 0.002)); }
                return col;
            }
            float3 Ident(float2 uv, float t)
            {
                float2 p = float2((uv.x - 0.5) * _Aspect, uv.y - 0.5);
                float3 col = lerp(float3(0.06, 0.0, 0.08), float3(0.25, 0.02, 0.18), saturate(0.6 - length(p)));
                float bands = step(0.5, frac(p.y * 22 - t * 0.6)); col += PINK * 0.08 * bands;
                float r = length(p), a = atan2(p.y, p.x);
                float petal = 0.16 + 0.05 * sin(a * 5 + t * 0.8) + 0.02 * sin(a * 11 - t);                 // rosa estilizada
                col = lerp(col, lerp(float3(0.5, 0.02, 0.15), PINK * 1.4, saturate(r / petal)), step(r, petal));
                col += CYAN * saturate(1 - abs(r - 0.28 - 0.01 * sin(t * 2)) * 140) * 1.2;
                col += VIOL * saturate(1 - abs(r - 0.34) * 200) * step(0.5, frac(a * 3.0 / 6.2832 * 8 + t * 0.3));
                return col;
            }
            fixed4 frag(v2f i) : SV_Target
            {
                float t = _Time.y + _Seed * 17.3;
                float2 uv = i.uv;
                float3 c;
                if (_Mode < 0.5) c = Synthwave(uv, t);
                else if (_Mode < 1.5) c = HUD(uv, t);
                else if (_Mode < 2.5) c = Spiral(uv, t);
                else if (_Mode < 3.5) c = EQ(uv, t);
                else if (_Mode < 4.5) c = BimboTV(uv, t);
                else if (_Mode < 5.5) c = Weather(uv, t);
                else if (_Mode < 6.5) c = Pitch(uv, t);
                else if (_Mode < 7.5) c = Tactical(uv, t);
                else c = Ident(uv, t);
                float scan = 0.82 + 0.18 * sin(uv.y * 900);
                float2 v = uv - 0.5; float vig = saturate(1 - dot(v, v) * 1.6);
                fixed4 col = fixed4(c * scan * vig * _Bright, 1);
                col.rgb = max(col.rgb, 0); if (any(isnan(col.rgb))) col.rgb = 0;   // nunca NaN (el bloom lo vuelve manchas blancas)
                UNITY_APPLY_FOG(i.fogCoord, col);
                return col;
            }
            ENDCG
        }
    }
}
