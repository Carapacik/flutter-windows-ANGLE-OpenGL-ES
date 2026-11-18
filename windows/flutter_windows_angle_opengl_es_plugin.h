#ifndef FLUTTER_PLUGIN_FLUTTER_WINDOWS_ANGLE_OPENGL_ES_PLUGIN_H_
#define FLUTTER_PLUGIN_FLUTTER_WINDOWS_ANGLE_OPENGL_ES_PLUGIN_H_

#include <flutter/method_channel.h>
#include <flutter/plugin_registrar_windows.h>

#include <flutter/texture_registrar.h>

#include <memory>

#include "messages.g.h"

namespace flutter_windows_angle_opengl_es {

class FlutterWindowsAngleOpenglEsPlugin
    : public flutter::Plugin,
      public FlutterWindowsAngleOpenglEsPluginApi {
 public:
  static void RegisterWithRegistrar(flutter::PluginRegistrarWindows* registrar);

  explicit FlutterWindowsAngleOpenglEsPlugin(
      flutter::PluginRegistrarWindows* registrar);

  ~FlutterWindowsAngleOpenglEsPlugin() override;

  // Disallow copy and assign.
  FlutterWindowsAngleOpenglEsPlugin(const FlutterWindowsAngleOpenglEsPlugin&) =
      delete;
  FlutterWindowsAngleOpenglEsPlugin& operator=(
      const FlutterWindowsAngleOpenglEsPlugin&) = delete;

  ErrorOr<int64_t> Render() override;

 private:
  struct RenderedTexture;
  std::shared_ptr<RenderedTexture> rendered_texture_;
  flutter::BinaryMessenger* messenger_;
  flutter::TextureRegistrar* texture_registrar_;
  flutter::MethodChannel<flutter::EncodableValue> channel_;
};

}  // namespace flutter_windows_angle_opengl_es

#endif  // FLUTTER_PLUGIN_FLUTTER_WINDOWS_ANGLE_OPENGL_ES_PLUGIN_H_
