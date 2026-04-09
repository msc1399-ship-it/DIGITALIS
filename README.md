# 💊 Auditoría de Compras Farmacia

Aplicación en **Streamlit** para auditar compras de farmacia a partir de albaranes de mayoristas (Bidafarma y Cofares), con normalización de datos, clasificación de líneas, detección de abonos y motor básico de costes.

## Funcionalidades actuales

- Subida de múltiples albaranes (`.xlsx` / `.xls`).
- Detección automática de proveedor.
- Normalización de columnas clave:
  - `cn`, `descripcion`, `unidades`, `bruto`, `neto`, `iva`, `descuento`, `proveedor`, `seccion_albaran`, `albaran`.
- Clasificación de líneas por proveedor:
  - **Bidafarma:** `bitransfer`, `avantia`, `especialidad`, `parafarmacia`, `club`.
  - **Cofares:** `nexo`, `transfer_diferido`, `especialidad`, `parafarmacia`.
- Identificación de abonos (`neto < 0`) y visualización específica.
- Cálculo de métricas globales:
  - bruto, neto, descuento, unidades, precio unitario y abonos.
- Resumen por proveedor y segmentación por tipo de línea.
- Carga opcional de condiciones (facturas / ICC) para estimar coste real.
- Bloque de conciliación Bidafarma:
  - subida de factura normal y factura transfer,
  - cruce de albaranes facturados vs albaranes cargados,
  - detección de descuadres,
  - detección automática de cargos para su prorrateo inicial.

## Motor de costes (versión inicial)

Puedes cargar un archivo `.csv`/`.xlsx` con estas columnas:

- `proveedor`
- `concepto`
- `porcentaje`
- `importe`

La app calcula:

- `coste_real_estimado = neto_base + cargos_estimados`

Donde `cargos_estimados` aplica porcentajes e importes fijos por proveedor (o globales).

## Ejecución local

1. Instala dependencias:

   ```bash
   pip install -r requirements.txt
   ```

2. Ejecuta la app:

   ```bash
   streamlit run streamlit_app.py
   ```

## Próximos pasos recomendados

- Integrar conciliación contra facturas reales.
- Añadir validaciones por proveedor (esquemas por plantilla).
- Incorporar tests automáticos para reglas de clasificación.
- Exportación de resultados a Excel/PDF.
