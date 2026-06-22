"""IMDB / JOB statistics provider -- the IMDB counterpart of stats.py.

Configured for the IMDB artifacts under the PathCE submodule (the GLogS IMDB catalog and
schema) and an IMDB relational statistics catalog. Paths can be overridden with the
ISPG_IMDB_* environment variables.

JOB (SQL) table -> IMDB property-graph mapping (the paper's SPJM mapping)
------------------------------------------------------------------------
- Tables read as vertices: title, name(=person), keyword, char_name, company_name,
  cast_info, movie_info, movie_info_idx, ...  (see TABLE_TO_LABEL)
- Tables that are not vertices become edges / R' relations: movie_companies, company_type,
  movie_keyword, movie_link, link_type, ...  (see NONVERTEX_TO_EDGE)
"""
from __future__ import annotations

import os

from stats import _PROJ_ROOT, _REF, GLOGS_BIN, Stats

IMDB_GLOGS_CATALOG = os.environ.get(
    "ISPG_IMDB_GLOGS_CATALOG", os.path.join(_REF, "catalogs", "imdb", "glogs", "imdb.bincode"))
IMDB_GLOGS_SCHEMA = os.environ.get(
    "ISPG_IMDB_GLOGS_SCHEMA", os.path.join(_PROJ_ROOT, "schemas", "imdb", "imdb_glogs_schema.json"))
IMDB_RELSTATS = os.environ.get(
    "ISPG_IMDB_RELSTATS", os.path.join(os.path.dirname(__file__), "catalogs", "imdb_relstats.json"))

# JOB relational table -> GLogS IMDB vertex label.
TABLE_TO_LABEL = {
    "aka_name": "akaName", "aka_title": "akaTitle", "cast_info": "castInfoVertex",
    "char_name": "character", "company_name": "companyName", "complete_cast": "complCastInfoVertex",
    "movie_info": "infoVertex", "movie_info_idx": "infoIdxVertex", "keyword": "keyword",
    "name": "person", "person_info": "personInfoVertex", "title": "title",
}
# JOB non-vertex tables -> the GLogS edge/relation they correspond to (used as R').
NONVERTEX_TO_EDGE = {
    "movie_companies": "title_movieCompanies_companyName",
    "company_type": "title_movieCompanies_companyName",
    "movie_keyword": "title_keywordEdge_keyword",
    "movie_link": "title_linkTypeEdge_title",
    "link_type": "title_linkTypeEdge_title",
}


class ImdbStats(Stats):
    """Same interface as Stats, configured for the IMDB artifacts under ref/."""

    def __init__(self):
        super().__init__(catalog_path=IMDB_RELSTATS,
                         glogs_catalog=IMDB_GLOGS_CATALOG,
                         glogs_schema=IMDB_GLOGS_SCHEMA,
                         glogs_bin=GLOGS_BIN)
