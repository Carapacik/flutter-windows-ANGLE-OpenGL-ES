import 'package:flutter_windows_angle_opengl_es/src/messages.g.dart';

/// Renders the ANGLE example into a Windows GPU texture.
final class FlutterWindowsAngleOpenglEs() {
  final _api = FlutterWindowsAngleOpenglEsPluginApi();

  /// Returns the texture ID for the triangle. Repeated calls reuse the texture.
  Future<int> render() => _api.render();
}
