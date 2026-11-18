import 'package:flutter_windows_angle_opengl_es/flutter_windows_angle_opengl_es.dart';
import 'package:material_ui/material_ui.dart';

void main() => runApp(const MyApp());

class const MyApp({super.key}) extends StatefulWidget {
  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState() extends State<MyApp> {
  late final Future<int?> _texture = _renderAfterFirstFrame();

  Future<int?> _renderAfterFirstFrame() async {
    await WidgetsBinding.instance.waitUntilFirstFrameRasterized;
    if (!mounted) {
      return null;
    }
    return await FlutterWindowsAngleOpenglEs().render();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      home: Scaffold(
        appBar: AppBar(title: const Text('Flutter Windows ANGLE OpenGL ES')),
        body: SizedBox.expand(
          child: FutureBuilder<int?>(
            future: _texture,
            builder: (context, snapshot) {
              if (snapshot.hasError) {
                return Center(
                  child: Text('ANGLE rendering failed: ${snapshot.error}'),
                );
              }
              final int? id = snapshot.data;
              if (id == null) {
                return const Center(child: CircularProgressIndicator());
              }
              return Texture(textureId: id, filterQuality: FilterQuality.high);
            },
          ),
        ),
      ),
    );
  }
}
