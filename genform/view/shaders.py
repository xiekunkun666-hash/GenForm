"""三维视图用的着色器源码 (GLSL 330): 背景渐变、纯色点线、实体的面、带宽度的线 (几何着色器把线段撑成四边形)。
线条的状态值: 0 普通 / 1 悬停 / 2 选中 / 3 正在画 / 4 标过尺寸的 / 5 尺寸线 (细)。"""

_BACK_VS = """#version 330 core
out vec2 uv;
void main(){ vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2); uv = p; gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0); }"""
_BACK_FS = """#version 330 core
in vec2 uv; uniform vec3 top; uniform vec3 bottom; uniform float spot; out vec4 Frag;
void main(){
    float t = smoothstep(0.0, 1.0, uv.y);
    if (spot > 0.5) t = 1.0 - smoothstep(0.0, 0.85, length((uv - vec2(0.5, 0.42)) * vec2(1.25, 1.0)));     // 中间一团亮, 四周暗下去
    Frag = vec4(mix(bottom, top, t), 1.0);
}"""

_FLAT_VS = """#version 330 core
layout(location=0) in vec3 pos; layout(location=1) in vec4 color;
uniform mat4 mvp; uniform float pointSize; out vec4 vColor; out vec3 vPos;
void main(){ vColor = color; vPos = pos; gl_Position = mvp * vec4(pos, 1.0); gl_PointSize = pointSize; }"""
_FLAT_FS = """#version 330 core
in vec4 vColor; in vec3 vPos; uniform float fade; out vec4 Frag;
void main(){
    float edge = fade > 0.0 ? 1.0 - smoothstep(0.55 * fade, fade, max(abs(vPos.x), abs(vPos.y))) : 1.0;
    Frag = vec4(vColor.rgb, vColor.a * edge);
}"""

_MESH_VS = """#version 330 core
layout(location=0) in vec3 pos; layout(location=1) in vec3 nrm; layout(location=2) in float state; layout(location=3) in vec3 tint;
uniform mat4 mvp; uniform mat4 model; uniform vec4 clip; out vec3 vN; out vec3 vP; out vec3 vTint; flat out float vState;
void main(){ vec4 world = model * vec4(pos, 1.0); vN = mat3(model) * nrm; vP = world.xyz; vState = state; vTint = tint;
    gl_Position = mvp * world; gl_ClipDistance[0] = dot(world, clip); }"""
_MESH_FS = """#version 330 core
in vec3 vN; in vec3 vP; in vec3 vTint; flat in float vState;
uniform vec3 eye; uniform vec3 base; uniform vec3 hover; uniform vec3 chosen;
uniform float flatShade; uniform float toon; uniform float useTint; uniform float alpha;
out vec4 Frag;
void main(){
    vec3 own = (useTint > 1.5 && vTint.r >= 0.0) ? vTint : base;      // 单独上了色的特征的面 (-1 = 零件的颜色)
    if (flatShade > 0.5) {                          // 消除隐藏线 / 隐藏线可见: 面只用来挡住后面的线, 不打光
        Frag = vec4(vState > 1.5 ? mix(base, chosen, 0.55) : (vState > 0.5 ? mix(base, hover, 0.45) : base), alpha);
        return;
    }
    vec3 N = normalize(vN);
    vec3 V = normalize(eye - vP);
    if (dot(N, V) < 0.0) N = -N;                    // 背面 (切开的内壁等) 也按朝向相机打光
    // 光跟着相机走 (主光偏右上, 补光偏左): 零件转到哪个角度都看得清, 没有照不到的黑面
    vec3 R = normalize(cross(V, vec3(0.0, 0.0, 1.0)) + vec3(1e-4, 0.0, 0.0));
    vec3 U = cross(R, V);
    vec3 L1 = normalize(V + R * 0.55 + U * 0.75);
    vec3 L2 = normalize(V - R * 0.80 - U * 0.20);
    float diffuse = 0.42 + 0.50 * max(dot(N, L1), 0.0) + 0.16 * max(dot(N, L2), 0.0);
    vec3 color = vState > 1.5 ? chosen : (vState > 0.5 ? hover : own);
    if (useTint > 0.5 && useTint < 1.5) color = vState > 1.5 ? mix(vTint, chosen, 0.55) : vTint;     // 云图: 每个顶点自己的颜色
    float spec = pow(max(dot(N, normalize(L1 + V)), 0.0), 40.0) * 0.16;
    if (toon > 0.5) { diffuse = 0.50 + 0.18 * floor(diffuse * 3.2); spec = 0.0; }      // 卡通: 明暗分成几档, 不要高光
    Frag = vec4(color * diffuse + vec3(spec * (alpha < 0.999 ? 3.0 : 1.0)), alpha);     // 玻璃: 高光亮一些, 才像玻璃
}"""

_LINE_VS = """#version 330 core
layout(location=0) in vec3 pos; layout(location=1) in float state;
uniform mat4 mvp; uniform vec4 clip; out float gState;
void main(){ gState = state; gl_Position = mvp * vec4(pos, 1.0); gl_ClipDistance[0] = dot(vec4(pos, 1.0), clip); }"""
_LINE_GS = """#version 330 core
layout(lines) in; layout(triangle_strip, max_vertices=4) out;
in float gState[]; uniform vec2 viewport; uniform float width; uniform float widthActive;
flat out float fState;
void main(){
    vec4 a = gl_in[0].gl_Position, b = gl_in[1].gl_Position;
    if (a.w <= 0.0 || b.w <= 0.0) return;           // 穿过相机平面的线段不画 (零件一般都在相机前面)
    vec2 sa = a.xy / a.w * viewport, sb = b.xy / b.w * viewport;
    vec2 along = sb - sa; float len = length(along);
    vec2 side = len > 1e-6 ? vec2(-along.y, along.x) / len : vec2(1.0, 0.0);
    float half = gState[0] > 4.5 ? width * 0.6 : (gState[0] > 0.5 && gState[0] < 3.5 ? widthActive : width);    // 5 = 尺寸线: 细
    vec2 off = side * half / viewport;
    // 每发一个顶点前都要重新给输出赋值 (发完就失效)
    float ca = gl_in[0].gl_ClipDistance[0], cb = gl_in[1].gl_ClipDistance[0];
    fState = gState[0]; gl_ClipDistance[0] = ca; gl_Position = vec4(a.xy + off * a.w, a.zw); EmitVertex();
    fState = gState[0]; gl_ClipDistance[0] = ca; gl_Position = vec4(a.xy - off * a.w, a.zw); EmitVertex();
    fState = gState[0]; gl_ClipDistance[0] = cb; gl_Position = vec4(b.xy + off * b.w, b.zw); EmitVertex();
    fState = gState[0]; gl_ClipDistance[0] = cb; gl_Position = vec4(b.xy - off * b.w, b.zw); EmitVertex();
    EndPrimitive();
}"""
_LINE_FS = """#version 330 core
flat in float fState; uniform vec3 base; uniform vec3 hover; uniform vec3 chosen; uniform vec3 draft; uniform vec3 defined; uniform float alpha;
out vec4 Frag;
void main(){
    vec3 color = fState > 3.5 ? defined : (fState > 2.5 ? draft : (fState > 1.5 ? chosen : (fState > 0.5 ? hover : base)));
    Frag = vec4(color, fState > 0.5 ? 1.0 : alpha);
}"""
