import io
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd

from modules.maestro_laboratorios import normalizar_cn


def _tag_local(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _row_dicts_from_xml_bytes(xml_bytes):
    root = ET.fromstring(xml_bytes)
    rows = []

    for child in list(root):
        values = {}
        for node in child.iter():
            if node is child:
                continue
            if list(node):
                continue
            text = (node.text or "").strip()
            if not text:
                continue
            values[_tag_local(node.tag).lower()] = text
        if values:
            rows.append(values)

    return rows


def _find_member(namelist, candidates):
    lowered = {name.lower(): name for name in namelist}
    for candidate in candidates:
        for lower_name, real_name in lowered.items():
            if candidate in lower_name:
                return real_name
    return None


def _pick_first(row, keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _build_laboratory_map(rows):
    mapping = {}

    code_candidates = [
        "codigo",
        "codigolaboratorio",
        "cod_laboratorio",
        "laboratorio",
        "id",
        "cod",
    ]
    name_candidates = [
        "descripcion",
        "des_laboratorio",
        "nombre",
        "nom_laboratorio",
        "laboratorio",
        "razon_social",
    ]

    for row in rows:
        code = _pick_first(row, code_candidates)
        name = _pick_first(row, name_candidates)
        if code and name:
            mapping[str(code).strip()] = str(name).strip()

    return mapping


def leer_nomenclator_aemps(file):
    nombre = str(getattr(file, "name", "")).lower()

    if hasattr(file, "seek"):
        file.seek(0)

    raw = file.read()
    if hasattr(file, "seek"):
        file.seek(0)

    prescripcion_rows = None
    lab_rows = []

    if nombre.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            member_prescripcion = _find_member(
                zf.namelist(),
                ["prescripcion.xml"],
            )
            member_laboratorios = _find_member(
                zf.namelist(),
                ["diccionario_laboratorios.xml"],
            )

            if not member_prescripcion:
                raise ValueError(
                    "El zip del Nomenclátor AEMPS no contiene Prescripcion.xml."
                )

            prescripcion_rows = _row_dicts_from_xml_bytes(zf.read(member_prescripcion))
            if member_laboratorios:
                lab_rows = _row_dicts_from_xml_bytes(zf.read(member_laboratorios))

    elif nombre.endswith(".xml"):
        prescripcion_rows = _row_dicts_from_xml_bytes(raw)
    else:
        raise ValueError(
            "Sube el zip oficial del Nomenclátor AEMPS o el fichero Prescripcion.xml."
        )

    if not prescripcion_rows:
        raise ValueError("No se han encontrado registros en el Nomenclátor AEMPS.")

    lab_map = _build_laboratory_map(lab_rows)

    registros = []
    for row in prescripcion_rows:
        cn = normalizar_cn(_pick_first(row, ["cod_nacion"]))
        descripcion = _pick_first(row, ["des_prese", "des_nomco"])
        lab_comercial = _pick_first(row, ["laboratorio_comercializador"])
        lab_titular = _pick_first(row, ["laboratorio_titular"])

        laboratorio = (
            lab_map.get(str(lab_comercial).strip()) if lab_comercial is not None else None
        )
        if not laboratorio and lab_titular is not None:
            laboratorio = lab_map.get(str(lab_titular).strip())
        if not laboratorio:
            laboratorio = str(lab_comercial or lab_titular or "").strip() or None

        if not cn or not descripcion:
            continue

        registros.append(
            {
                "cn": cn,
                "laboratorio_maestro": laboratorio,
                "descripcion_maestra": str(descripcion).strip(),
                "tipo_producto": "medicamento",
                "fuente_maestro": "aemps_nomenclator",
            }
        )

    if not registros:
        raise ValueError(
            "No se pudieron extraer códigos nacionales válidos del Nomenclátor AEMPS."
        )

    df = pd.DataFrame(registros)
    df = df.dropna(subset=["cn"])
    df = df.drop_duplicates(subset=["cn"], keep="first").reset_index(drop=True)
    return df
