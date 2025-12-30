ispg/imdb/imdb_sample_induced_bfs.py
Build a small induced subgraph for GLogS statistics.
--input-dir     Input directory (default: /dataset/imdb/imdb)
--output-dir    Output directory (default: /ispg/imdb/imdb_small_bfs)
--ratio         Induced subgraph sampling ratio (default: 0.00035)
--seed          Random seed / starting point (default: 42 for title)

ispg/imdb/imdb_reassign_vid_ldbc_style.py
Create globally contiguous IDs and de-duplicate.
--input-dir     Input directory (default: /imdb_small_bfs)
--output-dir    Output directory (default: /imdb_small_bfs_vid)
--schema        Schema file (no change needed for IMDB)

ispg/imdb/build_imdb_small_graph.sh
Build a graph from the dataset for GLogS analysis.
-d              Input directory (default: /imdb_small_bfs_vid)
-o              Output directory (default: /graphs/imdb_small/glogs/imdb_small)

ispg/imdb/build_imdb_small_catalog.sh
Build a catalog from the constructed graph using GLogS.
-t              Number of threads (default: 32)
-p              Output directory (default: /catalogs/imdb_small/glogs)


Additional Python dependencies (besides the repository README):
pip install sqlglot duckdb