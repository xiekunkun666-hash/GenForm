# -*- coding: utf-8 -*-
"""着色器程序的薄封装 (取自切片软件 Gen Pack 的 gl/shader_program.py)。"""
from OpenGL.GL import *


class ShaderProgram:
    def __init__(self, vs_src: str, fs_src: str, gs_src: str | None = None):
        self._handle = self._create(vs_src, fs_src, gs_src)

    def __enter__(self):
        glUseProgram(self._handle)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        glUseProgram(0)

    def loc(self, name):
        return glGetUniformLocation(self._handle, name)

    @staticmethod
    def _compile(src: str, kind):
        shader = glCreateShader(kind)
        glShaderSource(shader, src)
        glCompileShader(shader)
        if not glGetShaderiv(shader, GL_COMPILE_STATUS):
            raise RuntimeError(glGetShaderInfoLog(shader).decode())
        return shader

    def _create(self, vs: str, fs: str, gs: str | None):
        program = glCreateProgram()
        glAttachShader(program, self._compile(vs, GL_VERTEX_SHADER))
        if gs is not None:
            glAttachShader(program, self._compile(gs, GL_GEOMETRY_SHADER))
        glAttachShader(program, self._compile(fs, GL_FRAGMENT_SHADER))
        glLinkProgram(program)
        if not glGetProgramiv(program, GL_LINK_STATUS):
            raise RuntimeError(glGetProgramInfoLog(program).decode())
        return program
