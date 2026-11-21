// Bimbo Mansion — haz de luz falso (cono aditivo) y charco de luz en el piso, para los platos LED de fiesta.
// Malla del cono: uv.y = 0 en el plato, 1 en la punta lejana; uv.x alrededor. El color lo pone BMDiscoLights
// (material por luz, _Color). _Kind 0 = haz (se desvanece a lo largo y en los bordes), 1 = charco (disco radial).
Shader "BRTV/LightBeam"
{
    Properties
    {
        _Color ("Color", Color) = (1, 0.2, 0.7, 1)
        _Intensity ("Intensidad", Float) = 0.9
        _Kind ("Tipo (0 haz, 1 charco)", Float) = 0
    }
    SubShader
    {
        Tags { "Queue"="Transparent+2" "RenderType"="Transparent" "IgnoreProjector"="True" }
        Blend One One
        ZWrite Off
        Cull Off
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fog
            #pragma multi_compile_instancing
            #include "UnityCG.cginc"
            float4 _Color; float _Intensity, _Kind;
            struct appdata { float4 vertex : POSITION; float3 normal : NORMAL; float2 uv : TEXCOORD0; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct v2f { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float edge : TEXCOORD1; UNITY_FOG_COORDS(2) UNITY_VERTEX_OUTPUT_STEREO };
            v2f vert(appdata v)
            {
                v2f o; UNITY_SETUP_INSTANCE_ID(v); UNITY_INITIALIZE_OUTPUT(v2f, o); UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.pos = UnityObjectToClipPos(v.vertex); o.uv = v.uv;
                float3 wn = UnityObjectToWorldNormal(v.normal); wn *= rsqrt(max(dot(wn, wn), 1e-6));   // punta del cono: normal nula sin NaN
                float3 wp = mul(unity_ObjectToWorld, v.vertex).xyz;
                float3 V = _WorldSpaceCameraPos - wp; V *= rsqrt(max(dot(V, V), 1e-6));
                o.edge = saturate(abs(dot(wn, V)));            // de frente al borde del cono: más denso en el centro visual
                UNITY_TRANSFER_FOG(o, o.pos);
                return o;
            }
            fixed4 frag(v2f i) : SV_Target
            {
                float a;
                if (_Kind < 0.5) a = pow(saturate(1 - i.uv.y), 1.6) * pow(saturate(i.edge), 1.5) * 0.55;
                else { float r = length(i.uv - 0.5) * 2; a = pow(saturate(1 - r), 1.8) * 0.7; }
                fixed4 c = fixed4(_Color.rgb * a * _Intensity, 1);
                c.rgb = max(c.rgb, 0); if (any(isnan(c.rgb))) c.rgb = 0;   // nunca NaN: el bloom lo convierte en manchas blancas
                UNITY_APPLY_FOG_COLOR(i.fogCoord, c, fixed4(0, 0, 0, 0));
                return c;
            }
            ENDCG
        }
    }
}
