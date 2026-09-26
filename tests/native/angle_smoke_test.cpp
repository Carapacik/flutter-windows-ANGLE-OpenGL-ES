#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <d3d11.h>
#include <dxgi.h>
#include <wrl.h>

#include <array>
#include <cstring>
#include <iostream>
#include <stdexcept>

using Microsoft::WRL::ComPtr;

namespace {

constexpr EGLint kConfigAttributes[] = {EGL_SURFACE_TYPE,
                                        EGL_PBUFFER_BIT,
                                        EGL_RENDERABLE_TYPE,
                                        EGL_OPENGL_ES2_BIT,
                                        EGL_RED_SIZE,
                                        8,
                                        EGL_GREEN_SIZE,
                                        8,
                                        EGL_BLUE_SIZE,
                                        8,
                                        EGL_ALPHA_SIZE,
                                        8,
                                        EGL_NONE};
constexpr EGLint kContextAttributes[] = {EGL_CONTEXT_CLIENT_VERSION, 2,
                                         EGL_NONE};
constexpr EGLint kPbufferAttributes[] = {EGL_WIDTH, 8, EGL_HEIGHT, 8, EGL_NONE};
constexpr EGLint kSharedPbufferAttributes[] = {EGL_WIDTH,
                                               8,
                                               EGL_HEIGHT,
                                               8,
                                               EGL_TEXTURE_TARGET,
                                               EGL_TEXTURE_2D,
                                               EGL_TEXTURE_FORMAT,
                                               EGL_TEXTURE_RGBA,
                                               EGL_NONE};

void Check(bool ok, const char* operation) {
  if (!ok) {
    throw std::runtime_error(operation);
  }
}

PFNEGLGETPLATFORMDISPLAYEXTPROC GetPlatformDisplay() {
  auto function = reinterpret_cast<PFNEGLGETPLATFORMDISPLAYEXTPROC>(
      eglGetProcAddress("eglGetPlatformDisplayEXT"));
  Check(function != nullptr, "eglGetPlatformDisplayEXT");
  return function;
}

EGLConfig ChooseConfig(EGLDisplay display) {
  EGLConfig config = nullptr;
  EGLint count = 0;
  Check(eglChooseConfig(display, kConfigAttributes, &config, 1, &count) &&
            count == 1,
        "eglChooseConfig");
  return config;
}

void RenderAndRead(EGLDisplay display, EGLSurface surface, EGLContext context) {
  Check(eglMakeCurrent(display, surface, surface, context), "eglMakeCurrent");
  glViewport(0, 0, 8, 8);
  glClearColor(0.25f, 0.5f, 0.75f, 1.0f);
  glClear(GL_COLOR_BUFFER_BIT);
  glFinish();
  std::array<unsigned char, 4> rgba{};
  glReadPixels(4, 4, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
  Check(glGetError() == GL_NO_ERROR && rgba[0] > 60 && rgba[0] < 68 &&
            rgba[1] > 124 && rgba[1] < 132 && rgba[2] > 187 && rgba[2] < 195 &&
            rgba[3] == 255,
        "GLES2 readback");
}

void DestroyEGL(EGLDisplay display, EGLSurface surface, EGLContext context) {
  eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
  eglDestroyContext(display, context);
  eglDestroySurface(display, surface);
  eglTerminate(display);
}

bool RunGeneric(const EGLint* display_attributes) {
  EGLDisplay display = GetPlatformDisplay()(
      EGL_PLATFORM_ANGLE_ANGLE, EGL_DEFAULT_DISPLAY, display_attributes);
  if (display == EGL_NO_DISPLAY || !eglInitialize(display, nullptr, nullptr)) {
    return false;
  }
  EGLConfig config = ChooseConfig(display);
  EGLSurface surface =
      eglCreatePbufferSurface(display, config, kPbufferAttributes);
  Check(surface != EGL_NO_SURFACE, "eglCreatePbufferSurface");
  EGLContext context =
      eglCreateContext(display, config, EGL_NO_CONTEXT, kContextAttributes);
  Check(context != EGL_NO_CONTEXT, "eglCreateContext");
  RenderAndRead(display, surface, context);
  std::cout << "renderer: " << glGetString(GL_RENDERER) << '\n';
  DestroyEGL(display, surface, context);
  return true;
}

void RunD3D(bool warp, bool feature_level_9_3) {
  constexpr std::array<D3D_FEATURE_LEVEL, 4> kLevels = {
      D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_10_1, D3D_FEATURE_LEVEL_10_0,
      D3D_FEATURE_LEVEL_9_3};
  constexpr std::array<D3D_FEATURE_LEVEL, 1> kLevel9_3 = {
      D3D_FEATURE_LEVEL_9_3};
  const D3D_FEATURE_LEVEL* levels =
      feature_level_9_3 ? kLevel9_3.data() : kLevels.data();
  const UINT level_count =
      static_cast<UINT>(feature_level_9_3 ? kLevel9_3.size() : kLevels.size());
  ComPtr<ID3D11Device> device;
  ComPtr<ID3D11DeviceContext> device_context;
  Check(SUCCEEDED(D3D11CreateDevice(
            nullptr, warp ? D3D_DRIVER_TYPE_WARP : D3D_DRIVER_TYPE_HARDWARE,
            nullptr, D3D11_CREATE_DEVICE_BGRA_SUPPORT, levels, level_count,
            D3D11_SDK_VERSION, &device, nullptr, &device_context)),
        "D3D11CreateDevice");

  D3D11_TEXTURE2D_DESC desc{};
  desc.Width = desc.Height = 8;
  desc.MipLevels = desc.ArraySize = 1;
  desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
  desc.SampleDesc.Count = 1;
  desc.Usage = D3D11_USAGE_DEFAULT;
  desc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
  desc.MiscFlags = D3D11_RESOURCE_MISC_SHARED;
  ComPtr<ID3D11Texture2D> render_texture;
  ComPtr<ID3D11Texture2D> output_texture;
  Check(SUCCEEDED(device->CreateTexture2D(&desc, nullptr, &render_texture)),
        "CreateTexture2D render");
  Check(SUCCEEDED(device->CreateTexture2D(&desc, nullptr, &output_texture)),
        "CreateTexture2D output");
  ComPtr<IDXGIResource> resource;
  Check(SUCCEEDED(render_texture.As(&resource)), "IDXGIResource");
  HANDLE handle = nullptr;
  Check(SUCCEEDED(resource->GetSharedHandle(&handle)) && handle != nullptr,
        "GetSharedHandle");

  const EGLint display_attributes[] = {
      EGL_PLATFORM_ANGLE_TYPE_ANGLE,
      EGL_PLATFORM_ANGLE_TYPE_D3D11_ANGLE,
      EGL_PLATFORM_ANGLE_DEVICE_TYPE_ANGLE,
      warp ? EGL_PLATFORM_ANGLE_DEVICE_TYPE_D3D_WARP_ANGLE
           : EGL_PLATFORM_ANGLE_DEVICE_TYPE_HARDWARE_ANGLE,
      EGL_PLATFORM_ANGLE_MAX_VERSION_MAJOR_ANGLE,
      feature_level_9_3 ? 9 : EGL_DONT_CARE,
      EGL_PLATFORM_ANGLE_MAX_VERSION_MINOR_ANGLE,
      feature_level_9_3 ? 3 : EGL_DONT_CARE,
      EGL_NONE};
  EGLDisplay display = GetPlatformDisplay()(
      EGL_PLATFORM_ANGLE_ANGLE, EGL_DEFAULT_DISPLAY, display_attributes);
  Check(display != EGL_NO_DISPLAY && eglInitialize(display, nullptr, nullptr),
        "D3D11 eglInitialize");
  EGLConfig config = ChooseConfig(display);
  EGLSurface surface = eglCreatePbufferFromClientBuffer(
      display, EGL_D3D_TEXTURE_2D_SHARE_HANDLE_ANGLE, handle, config,
      kSharedPbufferAttributes);
  Check(surface != EGL_NO_SURFACE, "eglCreatePbufferFromClientBuffer");
  EGLContext context =
      eglCreateContext(display, config, EGL_NO_CONTEXT, kContextAttributes);
  Check(context != EGL_NO_CONTEXT, "eglCreateContext");
  RenderAndRead(display, surface, context);

  device_context->CopyResource(output_texture.Get(), render_texture.Get());
  desc.Usage = D3D11_USAGE_STAGING;
  desc.BindFlags = desc.MiscFlags = 0;
  desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
  ComPtr<ID3D11Texture2D> staging_texture;
  Check(SUCCEEDED(device->CreateTexture2D(&desc, nullptr, &staging_texture)),
        "CreateTexture2D staging");
  device_context->CopyResource(staging_texture.Get(), output_texture.Get());
  D3D11_MAPPED_SUBRESOURCE mapped{};
  Check(SUCCEEDED(device_context->Map(staging_texture.Get(), 0, D3D11_MAP_READ,
                                      0, &mapped)),
        "CopyResource/Map");
  const auto* bgra = static_cast<const unsigned char*>(mapped.pData) +
                     4 * mapped.RowPitch + 4 * 4;
  const bool copied = bgra[0] > 187 && bgra[0] < 195 && bgra[1] > 124 &&
                      bgra[1] < 132 && bgra[2] > 60 && bgra[2] < 68 &&
                      bgra[3] == 255;
  device_context->Unmap(staging_texture.Get(), 0);
  Check(copied, "D3D11 CopyResource readback");
  std::cout << "renderer: " << glGetString(GL_RENDERER) << '\n';
  DestroyEGL(display, surface, context);
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "usage: angle_smoke_test <d3d11|d3d11-9_3|warp|desktop-gl|"
                 "native-gles|vulkan|swiftshader>\n";
    return 1;
  }
  const char* backend = argv[1];
  try {
    bool available = true;
    if (std::strcmp(backend, "d3d11") == 0) {
      RunD3D(false, false);
    } else if (std::strcmp(backend, "d3d11-9_3") == 0) {
      RunD3D(false, true);
    } else if (std::strcmp(backend, "warp") == 0) {
      RunD3D(true, false);
    } else if (std::strcmp(backend, "desktop-gl") == 0) {
      const EGLint attributes[] = {EGL_PLATFORM_ANGLE_TYPE_ANGLE,
                                   EGL_PLATFORM_ANGLE_TYPE_OPENGL_ANGLE,
                                   EGL_NONE};
      available = RunGeneric(attributes);
    } else if (std::strcmp(backend, "native-gles") == 0) {
      const EGLint attributes[] = {EGL_PLATFORM_ANGLE_TYPE_ANGLE,
                                   EGL_PLATFORM_ANGLE_TYPE_OPENGLES_ANGLE,
                                   EGL_NONE};
      available = RunGeneric(attributes);
    } else if (std::strcmp(backend, "vulkan") == 0) {
      const EGLint attributes[] = {EGL_PLATFORM_ANGLE_TYPE_ANGLE,
                                   EGL_PLATFORM_ANGLE_TYPE_VULKAN_ANGLE,
                                   EGL_NONE};
      available = RunGeneric(attributes);
    } else if (std::strcmp(backend, "swiftshader") == 0) {
      const EGLint attributes[] = {
          EGL_PLATFORM_ANGLE_TYPE_ANGLE, EGL_PLATFORM_ANGLE_TYPE_VULKAN_ANGLE,
          EGL_PLATFORM_ANGLE_DEVICE_TYPE_ANGLE,
          EGL_PLATFORM_ANGLE_DEVICE_TYPE_SWIFTSHADER_ANGLE, EGL_NONE};
      Check(RunGeneric(attributes), "SwiftShader backend unavailable");
    } else {
      throw std::runtime_error("unknown backend");
    }
    if (!available) {
      std::cout << "UNAVAILABLE: " << backend << " runner is unavailable\n";
      return 2;
    }
    std::cout << "PASS: " << backend << " GLES2 render/readback/cleanup\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "FAIL: " << backend << ": " << error.what() << '\n';
    return 1;
  }
}
