# V90.bj — Android APK/Build Pipeline + Web UI Integration Foundation

- Added authenticated Web/Android UI integration manifest and build registry.
- Added `/web` ERP shell and static assets with health/build visibility.
- Added Android Gradle project skeleton with debug/release API base URL configuration.
- Added GitHub Actions Android APK build and Web asset validation workflow.
- Added migration 135 and UI build registry table.
- Added cumulative tests for routes, permissions, build registry and metadata.

## Verification

- 232/232 cumulative pytest tests passed; 18 pre-existing warnings.
- Migration range 61–135 is contiguous and checksums validate.
- Python compile check passed.
- GitHub CI gate passed.
- Android/Web integration assets are present.
- Release archive is free of local database, bytecode and cache artifacts.
