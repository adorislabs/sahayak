# Public static files embedded as Python data for Vercel bundling.
from src.public._data_ambiguity_map_anchor_schemes_html import FILENAME as _f1, CONTENT_TYPE as _c1, DATA as _d1
from src.public._data_ambiguity_map_global_html import FILENAME as _f2, CONTENT_TYPE as _c2, DATA as _d2
from src.public._data_report_pdf import FILENAME as _f3, CONTENT_TYPE as _c3, DATA as _d3
from src.public._data_rules_data_js import FILENAME as _f4, CONTENT_TYPE as _c4, DATA as _d4

FILES: dict[str, tuple[bytes, str]] = {
    _f1: (_d1, _c1),
    _f2: (_d2, _c2),
    _f3: (_d3, _c3),
    _f4: (_d4, _c4),
}
