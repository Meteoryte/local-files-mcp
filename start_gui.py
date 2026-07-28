try:
    from local_files_mcp.enhanced_gui_with_stops import main
except Exception:
    try:
        from local_files_mcp.enhanced_gui_plus import main
    except Exception:
        try:
            from local_files_mcp.enhanced_gui import main
        except Exception:
            from local_files_mcp.admin_gui import main

main()
