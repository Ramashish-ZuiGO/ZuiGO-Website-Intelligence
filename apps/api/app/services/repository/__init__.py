def __getattr__(name: str):
    import importlib

    module_map = {
        "validate_repository_path": "app.services.repository.path_safety",
        "is_git_repository": "app.services.repository.path_safety",
        "RepositoryScannerService": "app.services.repository.git_scanner",
        "FrameworkDetectionService": "app.services.repository.framework_detector",
        "ActionToCodeMatcherService": "app.services.repository.action_matcher",
    }
    if name in module_map:
        mod = importlib.import_module(module_map[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "validate_repository_path",
    "is_git_repository",
    "RepositoryScannerService",
    "FrameworkDetectionService",
    "ActionToCodeMatcherService",
]
