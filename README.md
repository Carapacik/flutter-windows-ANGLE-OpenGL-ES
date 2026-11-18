# flutter-windows-ANGLE-OpenGL-ES

OpenGL ES hardware accelerated rendering on Flutter Windows `Texture` Widget using ANGLE.

![Flutter Windows ANGLE OpenGL ES example](.github/example-windows.png)

## Introduction

[ANGLE (Almost Native Graphics Layer Engine)](https://github.com/google/angle) is used in this example, which translates these OpenGL ES calls to DirectX 11 (which Flutter Windows now supports) calls internally. The example uses the [new Direct3D texture interop capability for Flutter Windows](https://github.com/flutter/engine/pull/26840) added by [@jnschulze](https://github.com/jnschulze).

CI builds ANGLE from [`chromium/8127`](https://github.com/google/angle/tree/chromium/8127), the branch used by Chrome 158, currently the stable release for Windows. Each build resolves the branch head once and uses that commit for both architectures. The release archives record the commit in their manifests.

## Run

```bash
cd example
flutter run -d windows
```

## Build ANGLE

Requires Visual Studio C++ tools, Windows SDK `10.0.28000.x`, Git, Python 3.12 or later, and 7-Zip.

```cmd
python tools\angle.py setup
python tools\angle.py build x64
python tools\angle.py install x64
python tools\angle.py package x64
```

## Acknowlegements

- [@jnschulze](https://github.com/jnschulze) for working on [Windows: Add Direct3D texture interoperability support](https://github.com/flutter/engine/pull/26840) in [flutter/engine](https://github.com/flutter/engine).
- [@clarkezone](https://github.com/clarkezone) for awesome ANGLE + Windows article at [A common OpenGL renderer for UWP and Win32 using ANGLE and Win.UI.Composition](https://clarkezone.github.io/angle/2020/02/24/angle.html).
- [media-kit](https://github.com/media-kit/media-kit) for the Windows shared-texture implementation.

## References

- [Example project showing usage of ANGLE on Windows from @clarkezone](https://github.com/clarkezone/anglehosting).
- [Interop-with-other-DirectX-code section in Microsoft's ANGLE repository](https://github.com/Microsoft/angle/wiki/Interop-with-other-DirectX-code).
- [HelloTriangle.cpp from ANGLE repository](https://github.com/google/angle/blob/main/samples/hello_triangle/HelloTriangle.cpp).
