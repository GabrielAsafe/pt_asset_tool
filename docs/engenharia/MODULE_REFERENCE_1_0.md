# PT Asset Tool R14 1.0.0 — Referência de Módulos

Inventário automático de 153 módulos Python diretamente em `app/pt_asset_tool/`. O mapa conceitual detalhado continua em `MAPA_MODULOS_SCRIPTS.md`.

| Módulo | Família | Símbolos públicos principais |
|---|---|---|
| `__init__.py` | Core / misc | — |
| `__main__.py` | Core / misc | — |
| `affine_animation_selftest.py` | Core / misc | `run_affine_animation_selftest()` |
| `affine_factor.py` | Core / misc | `transpose()`, `mul()`, `det()`, `max_abs_diff()`, `svd_affine_split()` |
| `aggregation.py` | Core / misc | `HashStats`, `HashCache`, `build_player_class_aggregation()` |
| `animation_certification.py` | Animation | `build_animation_certification_plan()` |
| `animation_corpus.py` | Animation | `audit_animation_corpus()` |
| `animation_pose_devtest.py` | Animation | `choose_animation_pose_representatives()`, `filter_animation_pose_physical_representatives()`, `choose_animation_pose_physical_representatives()`, `run_animation_pose_automated_devtest()`, `run_animation_pose_automated_devtest_batch()` |
| `animation_source_regression.py` | Animation | `audit_animation_source_regression()` |
| `app_config.py` | Core / misc | `config_path()`, `load_config()`, `save_client_root()`, `clear_client_root()`, `candidate_client_roots_with_source()`, `candidate_client_roots()` |
| `authoring.py` | Core / misc | `normalize_lod_groups()`, `lod_groups_signature()`, `build_selected_authoring_context()`, `build_standalone_rigid_authoring_context()`, `verify_selected_authoring_context()`, `verify_selected_context_for_asset()` |
| `binding_coverage.py` | Core / misc | `audit_binding_coverage()` |
| `blender_workspace.py` | Core / misc | `asset_workspace_name()`, `blender_edit_root()`, `write_workspace_info()` |
| `build_provenance.py` | Core / misc | `sha256_file()`, `provenance_path()`, `write_build_provenance()`, `verify_build_provenance()` |
| `certification.py` | Core / misc | `CertificationRegistry` |
| `class_ui_alias_audit.py` | Core / misc | `audit_class_ui_aliases()` |
| `class_ui_alias_canonicalize.py` | Core / misc | `canonicalize_class_ui_alias_only()` |
| `cli.py` | Core / misc | `make_context()`, `table()`, `cmd_doctor()`, `cmd_audit_physique()`, `cmd_audit_animation_certification_plan()`, `cmd_audit_object_local()` |
| `client_manifest_evidence.py` | Core / misc | `parse_fixed_manifest()`, `audit_client_manifests()` |
| `config.py` | Core / misc | `Settings` |
| `contract_graph.py` | Core / misc | `ContractNode`, `ContractEdge`, `ContractGraph` |
| `deployment.py` | Core / misc | `plan_deployment()`, `prepare_deployment_transaction()`, `verify_deployment_transaction()`, `simulate_deployment_transaction()`, `classify_client_transaction_state()`, `plan_restore_transaction()` |
| `development_readiness.py` | Core / misc | `audit_development_readiness()` |
| `enrichment_vendor_adapter.py` | Core / misc | `generate_migration_plan()`, `build_dependency_graph()` |
| `entity_catalog.py` | Core / misc | `load_entity_seed()`, `enrich_entities_with_registry()`, `build_live_entities()`, `query_entities()`, `entity_detail()` |
| `environment_validation.py` | Core / misc | `run_environment_validation()` |
| `general_asset_census.py` | Core / misc | `audit_general_asset_census()`, `query_general_asset_census()` |
| `general_asset_recovery.py` | Core / misc | `RecoveryApplyRolledBackError`, `recover_closed_general_asset_bundles()` |
| `integration_regression_auto.py` | Core / misc | `run_integration_regression_auto()` |
| `inx_writer.py` | Core / misc | `encode_start()`, `encode_end()`, `rebuild_semantic_bytes()`, `validate_noop_roundtrip()`, `patch_motion()` |
| `mixed_authoring_candidate.py` | Core / misc | `analyze_mixed_source()`, `plan_mixed_saved_blender_candidate()`, `validate_mixed_candidate_output()`, `build_mixed_candidate_step_command()` |
| `mixed_real_devtest.py` | Core / misc | `choose_mixed_physique_representatives()`, `mixed_skeleton_candidates()`, `choose_mixed_physical_context()`, `run_mixed_physique_physical_automated_devtest()`, `run_mixed_physique_physical_automated_devtest_batch()` |
| `mixed_synthetic_devtest.py` | Core / misc | `run_mixed_physique_synthetic_devtest()` |
| `model062_corpus.py` | Model0.62 | `audit_model062_physical_corpus()` |
| `model062_material_devtest.py` | Model0.62 | `choose_model062_material_representatives()`, `run_model062_material_automated_devtest()`, `run_model062_material_automated_devtest_batch()`, `choose_all_model062_material_representatives()`, `audit_model062_material_physical_corpus()` |
| `model062_material_writer.py` | Model0.62 | `locate_materials()`, `rebuild_material_fields()`, `verify_material_candidate()` |
| `model062_texture_audit.py` | Model0.62 | `audit_model062_texture_presence()` |
| `monster_npc_census.py` | Core / misc | `sha256_file()`, `snapshot()`, `normalize_path()`, `build_index()`, `detect_physical_family()`, `extract_refs()` |
| `motion_core.py` | Core / misc | `inx_speed_sum()`, `parse_inx_link_header()`, `verified_inx_link_target()`, `load_smb_evaluator()`, `smb_skeleton_signature()`, `load_motion_system()` |
| `multilayer_texlink.py` | Core / misc | `parse_multilayer_semantics()`, `compact_semantics()`, `audit_multilayer_semantics_corpus()` |
| `object_local.py` | Object-local transforms | `quat_slerp()`, `quat_to_matrix4()`, `quat_to_matrix4_raw()`, `matrix4_transpose()`, `matrix4_inverse()`, `matrix4_identity_error()` |
| `object_local_audit.py` | Object-local transforms | `audit_object_local()` |
| `object_local_corpus.py` | Object-local transforms | `audit_object_local_physical_corpus()` |
| `object_local_devtest.py` | Object-local transforms | `run_object_local_automated_devtest()`, `choose_object_local_representatives()`, `run_object_local_automated_devtest_batch()` |
| `object_local_writer.py` | Object-local transforms | `patch_existing_object_local_key()`, `audit_object_local_writer_corpus()` |
| `official_character_donor_census.py` | Official donor/container forensics | `run()`, `main()` |
| `official_character_physical_compatibility.py` | Official donor/container forensics | `run()`, `main()` |
| `official_container_character_atlas.py` | Official donor/container forensics | `run()`, `main()` |
| `official_container_entry_recovery.py` | Official donor/container forensics | `run()`, `main()` |
| `official_container_record_index.py` | Official donor/container forensics | `run()`, `main()` |
| `official_payload_provenance_extraction.py` | Official donor/container forensics | `run()`, `main()` |
| `official_payload_source_locator.py` | Official donor/container forensics | `run()`, `main()` |
| `official_update_manifest_pack_correlation.py` | Official donor/container forensics | `run()`, `main()` |
| `physical_regression_auto.py` | Core / misc | `run_physical_regression_auto()` |
| `physique_audit.py` | Core / misc | `audit_physique_modes()` |
| `player_class_motion_contract.py` | Core / misc | `parse_reference_class_configs()`, `audit_class_motion_contract()` |
| `player_scale_witness.py` | Core / misc | `scan_scale_containers()`, `build_scale_container_bake_payload()`, `choose_player_scale_witness()`, `run_player_scale_witness()` |
| `profile_authoring.py` | Profiles/LOD | `plan_profile_authoring_context()` |
| `profile_candidates.py` | Profiles/LOD | `discover_profile_candidates()` |
| `profile_registry.py` | Profiles/LOD | `CharacterProfile`, `CharacterProfileRegistry` |
| `rare_outliers.py` | Core / misc | `audit_rare_outliers_and_tga()` |
| `rare_rigid_binding.py` | Rare rigid / controlled writer research | `audit_rare_rigid_binding()` |
| `rare_rigid_context.py` | Rare rigid / controlled writer research | `parse_model062_physique_context()`, `audit_rare_rigid_context()` |
| `rare_rigid_cross_object_interactive_candidate.py` | Rare rigid / controlled writer research | `discover_manual_uniform_transaction()`, `run()`, `main()` |
| `rare_rigid_cross_object_live_writer_candidate.py` | Rare rigid / controlled writer research | `write_at_dragon_cross_object_candidate_workspace()`, `run()`, `main()` |
| `rare_rigid_cross_object_probe.py` | Rare rigid / controlled writer research | `discover_cross_object_representatives()`, `patch_cross_object_transaction()`, `compare_cross_object_transaction()`, `run()`, `main()` |
| `rare_rigid_cross_object_production.py` | Rare rigid / controlled writer research | `load_and_validate_cross_policy()`, `write_cross_object_promoted()`, `write_production_dispatch()` |
| `rare_rigid_cross_object_production_promotion.py` | Rare rigid / controlled writer research | `run()`, `main()` |
| `rare_rigid_cross_object_saved_blender_candidate.py` | Rare rigid / controlled writer research | `run()`, `main()` |
| `rare_rigid_edit.py` | Rare rigid / controlled writer research | `plan_requested_at_dragon_edit()`, `prepare_at_dragon_edit_workspace()`, `write_at_dragon_edit_workspace()`, `audit_rare_rigid_edit_workflow()` |
| `rare_rigid_extent_bridge.py` | Rare rigid / controlled writer research | `choose_extent_witness()`, `patch_extent_bridge()`, `compare_extent_bridge()`, `audit_rare_rigid_outward_extent_roundtrip()` |
| `rare_rigid_geometry.py` | Rare rigid / controlled writer research | `audit_rare_rigid_geometry_preflight()` |
| `rare_rigid_large_interactive_candidate.py` | Rare rigid / controlled writer research | `run()`, `main()` |
| `rare_rigid_large_live_writer_candidate.py` | Rare rigid / controlled writer research | `run_audit()`, `main()` |
| `rare_rigid_large_production.py` | Rare rigid / controlled writer research | `load_and_validate_policy()`, `production_widening()`, `write_promoted()` |
| `rare_rigid_large_production_promotion.py` | Rare rigid / controlled writer research | `run()`, `main()` |
| `rare_rigid_large_saved_blender_candidate.py` | Rare rigid / controlled writer research | `run_audit()`, `main()` |
| `rare_rigid_large_transaction_probe.py` | Rare rigid / controlled writer research | `discover_large_representatives()`, `run_probe()`, `main()` |
| `rare_rigid_multibone_bridge.py` | Rare rigid / controlled writer research | `analyze_at_dragon_multibone()`, `audit_rare_rigid_multibone_bridge()` |
| `rare_rigid_multibone_extent_interactive_candidate.py` | Rare rigid / controlled writer research | `run()`, `main()` |
| `rare_rigid_multibone_extent_live_writer_candidate.py` | Rare rigid / controlled writer research | `write_at_dragon_multibone_outward_extent_candidate_workspace()`, `run()`, `main()` |
| `rare_rigid_multibone_extent_probe.py` | Rare rigid / controlled writer research | `discover_witnesses()`, `run()`, `main()` |
| `rare_rigid_multibone_extent_production.py` | Rare rigid / controlled writer research | `load_and_validate_extent_policy()`, `write_extent_promoted()`, `write_production_dispatch()` |
| `rare_rigid_multibone_extent_production_promotion.py` | Rare rigid / controlled writer research | `run()`, `main()` |
| `rare_rigid_multibone_extent_saved_blender_candidate.py` | Rare rigid / controlled writer research | `run()`, `main()` |
| `rare_rigid_multibone_roundtrip.py` | Rare rigid / controlled writer research | `patch_guarded_multibone()`, `compare_guarded_multibone()`, `audit_rare_rigid_guarded_multibone_roundtrip()` |
| `rare_rigid_multivertex.py` | Rare rigid / controlled writer research | `plan_requested_at_dragon_transaction()`, `patch_guarded_multivertex()`, `compare_guarded_multivertex()`, `discover_transaction_representatives()`, `discover_uniform_translation_pair()` |
| `rare_rigid_normal_bridge.py` | Rare rigid / controlled writer research | `choose_normal_bridge_witness()`, `patch_normal_bridge()`, `compare_normal_bridge()`, `audit_rare_rigid_normal_provenance_roundtrip()` |
| `rare_rigid_preview.py` | Rare rigid / controlled writer research | `parse_inx_model_groups()`, `choose_root_lod()`, `audit_rare_rigid_preview()`, `view_rare_rigid_preview()` |
| `rare_rigid_roundtrip.py` | Rare rigid / controlled writer research | `choose_single_bone_witness()`, `patch_single_bone_witness()`, `compare_single_bone_output()`, `audit_rare_rigid_single_bone_roundtrip()` |
| `rare_support.py` | Core / misc | `prepare_model062_tooling_source()`, `decode_ship_bmp_bytes()`, `build_ship_bmp_bytes()`, `decode_ship_bmp_exact()`, `audit_rare_support()` |
| `registry.py` | Core / misc | `Asset`, `AssetRegistry` |
| `release_1_auto.py` | Core / misc | `run_release_1_automated_gate()` |
| `release_1_coverage.py` | Core / misc | `content_domain_from_values()`, `content_domain()`, `build_release_1_coverage()`, `build_release_1_automated_gate_plan()`, `write_json()` |
| `release_scope.py` | Core / misc | — |
| `resolver.py` | Core / misc | `ClientResolver` |
| `rigid_authoring_candidate.py` | Rigid Model0.62 | `inspect_rigid_candidate_scope()`, `plan_rigid_saved_blender_candidate()`, `build_rigid_candidate_blender_command()`, `validate_rigid_candidate_output()` |
| `rigid_authoring_evidence.py` | Rigid Model0.62 | `rigid_candidate_context_key()`, `verify_rigid_candidate_artifact()`, `prepare_rigid_candidate_review_workspace()`, `verify_rigid_candidate_review_workspace()`, `build_candidate_provenance_evidence()`, `build_rigid_authoring_certification_plan()` |
| `rigid_authoring_stress.py` | Rigid Model0.62 | `inspect_rigid_profile_stress_scope()`, `plan_rigid_profile_stress_candidate()`, `validate_rigid_profile_stress_output()`, `stress_context_key()` |
| `rigid_context_census.py` | Rigid Model0.62 | `audit_rigid_context_census()` |
| `rigid_model_info.py` | Rigid Model0.62 | `normalize_lod_groups()`, `config_semantic_payload()`, `config_semantic_signature()`, `config_semantic_id()`, `logical_smd_node_names()`, `model_info_inx_configs()` |
| `rigid_profile_devtest.py` | Rigid Model0.62 | `run_rigid_profile_automated_devtest()`, `run_rigid_profile_automated_devtest_batch()` |
| `rigid_semantic_devtest.py` | Rigid Model0.62 | `run_rigid_semantic_automated_devtest()`, `run_rigid_semantic_automated_devtest_batch()` |
| `semantic_census.py` | Core / misc | `Classification`, `classify_semantic()`, `physical_probe()`, `run_census()`, `main()` |
| `semantic_path.py` | Core / misc | `semantic_group_for_path()`, `entity_folder_for_path()` |
| `server_bundle_census.py` | Server/enrichment | `audit_server_entity_bundles()` |
| `server_design_auto.py` | Server/enrichment | `run_server_design_auto()` |
| `server_environment_validation.py` | Server/enrichment | `run_server_environment_validation()` |
| `server_field_census.py` | Server/enrichment | `audit_server_field_bundles()` |
| `server_field_editor.py` | Server/enrichment | `inspect_field_metadata()`, `stage_spm_text()`, `stage_spp_records()`, `stage_spc_clone()` |
| `server_inventory.py` | Server/enrichment | `audit_server_inventory()` |
| `server_item_census.py` | Server/enrichment | `audit_server_item_bundles()` |
| `server_lifecycle.py` | Server/enrichment | `ServerPathClassification`, `classify_server_path()`, `is_hard_excluded_server_path()` |
| `server_ui.py` | Server/enrichment | `server_report_rows()`, `build_server_ui_summary()` |
| `skill_contract_census.py` | Core / misc | `PhysicalResolution`, `PhysicalSource`, `audit_player_class_contracts()` |
| `smb_writer.py` | Core / misc | `parse_smb_structural()`, `first_editable_key()`, `validate_track_roundtrip()`, `patch_key()` |
| `source_catalog.py` | Source evidence | `SourceTree`, `configured_source_roots()`, `require_source_trees()`, `iter_source_files()`, `read_source_text()`, `source_rel()`, `source_tree_summary()` |
| `source_contract_census.py` | Source evidence | `audit_source_contracts()` |
| `source_evidence.py` | Source evidence | `EvidenceRef`, `parse_reference_skill_catalog()`, `parse_skill_motion_registry()`, `scan_source_evidence()` |
| `stage072_area.py` | Stage0.72 | `analyze_stage072_stagearea()`, `audit_stage072_stagearea_rebuild()` |
| `stage072_authoring_candidate.py` | Stage0.72 | `plan_stage072_saved_blender_candidate()`, `build_stage072_edit_extract_command()`, `apply_stage072_candidate_witness()` |
| `stage072_corpus.py` | Stage0.72 | `parse_stage072()`, `audit_stage072_physical_corpus()` |
| `stage072_geometry.py` | Stage0.72 | `select_stage072_geometry_witness()`, `strict_write_stage072_geometry_witness()`, `compare_stage072_geometry_roundtrip()` |
| `stage072_material_devtest.py` | Stage0.72 | `run_stage072_material_automated_devtest()`, `run_stage072_material_automated_devtest_batch()`, `audit_stage072_material_physical_corpus()` |
| `stage072_material_writer.py` | Stage0.72 | `locate_stage_materials()`, `rebuild_stage_material_fields()`, `verify_stage_material_candidate()` |
| `stage072_normals.py` | Stage0.72 | `analyze_stage072_normals()`, `audit_stage072_normals()` |
| `stage072_roundtrip.py` | Stage0.72 | `strict_write_stage072_uv_witness()`, `compare_stage072_uv_roundtrip()` |
| `stage072_semantic_devtest.py` | Stage0.72 | `run_stage072_automated_devtest()`, `run_stage072_automated_devtest_batch()` |
| `stage072_texture_audit.py` | Stage0.72 | `runtime_trailing_space_alias()`, `serialized_reference_shape()`, `audit_stage072_texture_presence()` |
| `standalone_animation_devtest.py` | Core / misc | `audit_smb_animation_corpus()`, `choose_standalone_animation_representatives()`, `run_standalone_animation_pose_devtest()`, `run_standalone_animation_pose_devtest_batch()` |
| `standalone_rigid_devtest.py` | Core / misc | `authorable_lod_model_info_contexts()`, `model_info_lod_context_available()`, `model_info_lod_config_available()`, `standalone_rigid_context_eligible()`, `series_sibling_consensus_candidate()`, `structural_twin_skeleton_candidate()` |
| `static_authoring_candidate.py` | Core / misc | `plan_static_saved_blender_candidate()`, `validate_static_candidate_output()`, `build_static_candidate_blender_command()` |
| `static_roundtrip.py` | Core / misc | `compare_static_roundtrip()` |
| `static_semantic_devtest.py` | Core / misc | `validate_static_stress_output()`, `choose_static_semantic_representatives()`, `run_static_semantic_automated_devtest()`, `run_static_semantic_automated_devtest_batch()`, `audit_model062_static_physical_corpus()` |
| `superset_aggregation.py` | Core / misc | `TreeFile`, `parse_labeled_roots()`, `classify_client_path()`, `normalize_server_relative()`, `classify_server_path()`, `build_tree_superset()`, `build_client_superset()` |
| `texlink_corpus.py` | Core / misc | `parse_texlink_file()`, `audit_multilayer_texlink_corpus()` |
| `texlink_devtest.py` | Core / misc | `choose_multilayer_representatives()`, `run_multilayer_texlink_automated_devtest_batch()` |
| `texlink_roundtrip.py` | Core / misc | `strict_write_texlink_uv_witness()`, `compare_texlink_roundtrip()` |
| `texture_codec_devtest.py` | Core / misc | `audit_proprietary_texture_codecs()`, `audit_proprietary_texture_exact_regressions()`, `audit_proprietary_texture_physical_corpus()` |
| `texture_overlay.py` | Core / misc | `face_texture_references_model062()`, `prepare_texture_overlay()`, `classify_stage072_texture_transport_failures()`, `prepare_stage072_texture_overlay()` |
| `tree_compare.py` | Core / misc | `FileInfo`, `sha256_file()`, `compare_trees()`, `write_outputs()`, `cli_main()` |
| `ui_actions.py` | GUI/application UI | `ActionSpec`, `public_action_specs()`, `build_command()` |
| `ui_app.py` | GUI/application UI | `UIContext`, `UIHandler`, `run_ui()` |
| `ui_capabilities.py` | GUI/application UI | `capabilities_for_asset()` |
| `ui_catalog.py` | GUI/application UI | `CatalogStats`, `UIStateStore`, `CatalogIndex`, `extension_description()`, `infer_physical_family()`, `infer_folder_bucket()`, `infer_semantics()`, `sniff_physical_hint()`, `infer_capabilities()` |
| `ui_image.py` | GUI/application UI | `PreviewDecodeError`, `tga_bytes_to_png_bytes()`, `tga_to_png_bytes()`, `preview_image_bytes()` |
| `ui_jobs.py` | GUI/application UI | `Job`, `JobManager` |
| `update_tmp_lh5_decode.py` | Update.tmp/container forensics | `run()`, `main()` |
| `update_tmp_lha_forensics.py` | Update.tmp/container forensics | `run()`, `main()` |
| `utils.py` | Core / misc | `norm_path()`, `low_path()`, `sha256_file()`, `stable_id()`, `utc_now()`, `read_json()` |
| `validation.py` | Core / misc | `ValidationContext`, `ValidationRunner`, `rigid_model_info_options()` |
| `workflow_dispatch.py` | Core / misc | `build_plan()` |
| `writer_corpus_audit.py` | Core / misc | `audit_inx_writer_corpus()`, `audit_smb_writer_corpus()`, `audit_inx_writer_edit_corpus()`, `audit_smb_writer_edit_corpus()`, `audit_motion_writer_semantic_edit_corpus()` |
