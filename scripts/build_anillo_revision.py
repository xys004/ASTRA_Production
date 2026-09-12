from pathlib import Path
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    PageBreak,
    Table,
    TableStyle,
)


ROOT = Path(r"C:\Users\Nelson\Dev\ASTRA")
INPUT = Path(r"C:\Users\Nelson\Downloads\anillo_reservorios_010826.pdf")
OUT = ROOT / "output" / "pdf"
OUT.mkdir(parents=True, exist_ok=True)

MARKED = OUT / "anillo_reservorios_010826_revision_marcada.pdf"
EMAIL = OUT / "anillo_reservorios_010826_correo_evaluacion.txt"
SUPPLEMENT = OUT / "anillo_reservorios_010826_texto_revisado_sugerido.pdf"


def make_overlay(page_number, callouts):
    """Create a transparent annotation overlay for one original page."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle("Revision marcada - Anillo de Aharonov-Bohm")

    c.setFillColor(colors.Color(1, 0.92, 0.15, alpha=0.24))
    c.setStrokeColor(colors.Color(0.82, 0.27, 0.05, alpha=0.75))
    c.setLineWidth(1.1)
    for item in callouts:
        x, y, w, h, label = item
        try:
            c.setFillAlpha(0.24)
            c.setStrokeAlpha(0.75)
        except AttributeError:
            pass
        c.roundRect(x, y, w, h, 4, fill=1, stroke=1)
        c.setFillColor(colors.Color(0.55, 0.08, 0.02, alpha=0.92))
        c.setFont("Helvetica-Bold", 6.8)
        c.drawString(x + 3, y + h - 9, label)
        c.setFillColor(colors.Color(1, 0.92, 0.15, alpha=0.24))

    # Small non-intrusive footer mark.
    c.setFillColor(colors.Color(0.25, 0.25, 0.25, alpha=0.75))
    c.setFont("Helvetica", 6.5)
    c.drawRightString(570, 16, f"Revision marcada | pagina {page_number}")
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


CALL_OUTS = {
    # Coordinates use letter points, origin at lower left.
    3: [
        (48, 606, 255, 112, "CRITICO: REPRESENTACION 4N")
    ],
    4: [
        (48, 118, 255, 178, "CRITICO: MU_EQ Y MEDIO LLENADO"),
        (318, 466, 245, 155, "CORREGIR: SALTOS DE MU_EQ"),
    ],
    6: [
        (48, 214, 255, 177, "ACOTAR: GAMMA* DEPENDE DEL PROTOCOLO"),
        (318, 330, 245, 188, "ACOTAR: ASIMETRIA DE CONTACTOS"),
    ],
    7: [
        (318, 410, 245, 170, "EVITAR: 'DOMINANTE' SIN MISMA METRICA"),
    ],
    8: [
        (48, 410, 516, 70, "REVISAR: FIGURA 3 SUMA IP + IL"),
    ],
    9: [
        (48, 240, 516, 55, "REVISAR: FIGURA 4 Y MU_EQ CONSTANTE"),
    ],
    10: [
        (48, 62, 516, 110, "MAQUETACION: PAGINA SUBUTILIZADA"),
    ],
}


def build_marked_pdf():
    reader = PdfReader(str(INPUT))
    writer = PdfWriter()
    for idx, page in enumerate(reader.pages, start=1):
        if idx in CALL_OUTS:
            page.merge_page(make_overlay(idx, CALL_OUTS[idx]))
        writer.add_page(page)

    # Append a compact change log to make the markup actionable.
    notes = make_change_log_pdf()
    notes_reader = PdfReader(str(notes))
    for page in notes_reader.pages:
        writer.add_page(page)
    with MARKED.open("wb") as f:
        writer.write(f)


def make_change_log_pdf():
    path = OUT / "_anillo_change_log.pdf"
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="Small", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9.2, leading=12, spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name="SmallBold", parent=styles["Small"], fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="TitleCenter", parent=styles["Title"], alignment=TA_CENTER,
        fontName="Helvetica-Bold", fontSize=18, leading=22, spaceAfter=12,
    ))
    styles.add(ParagraphStyle(
        name="H2Custom", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=12, leading=15, spaceBefore=8, spaceAfter=6,
    ))

    doc = SimpleDocTemplate(
        str(path), pagesize=letter, rightMargin=48, leftMargin=48,
        topMargin=44, bottomMargin=42,
        title="Registro de cambios sugeridos",
        author="Revision editorial",
    )
    story = []
    story.append(Paragraph("Registro de cambios sugeridos", styles["TitleCenter"]))
    story.append(Paragraph(
        "Este suplemento acompana la version marcada del PDF. Las paginas originales se conservan; los resaltados indican los lugares que requieren correccion o acotacion.",
        styles["Small"],
    ))
    story.append(Spacer(1, 6))
    rows = [
        [Paragraph("Prioridad", styles["SmallBold"]), Paragraph("Ubicacion", styles["SmallBold"]), Paragraph("Cambio", styles["SmallBold"])],
        [Paragraph("P0", styles["SmallBold"]), Paragraph("pp. 3-4, Fig. 4", styles["Small"]), Paragraph("Resolver la contradiccion de mu_eq. El Hamiltoniano publicado es bipartito y, a medio llenado, impone mu_eq = 0. Si el codigo usa una matriz 4N, documentar su duplicacion y normalizacion.", styles["Small"])],
        [Paragraph("P0", styles["SmallBold"]), Paragraph("Sec. VII.F", styles["Small"]), Paragraph("Redefinir Gamma* como umbral dependiente del protocolo: IP se maximiza sobre flujo, mientras IL se evalua en un flujo y voltaje fijos.", styles["Small"])],
        [Paragraph("P0", styles["SmallBold"]), Paragraph("Sec. VI-VIII", styles["Small"]), Paragraph("Publicar codigo, malla espectral, limites de banda WBA, procedimiento eta -> 0 y barras de error reproducibles.", styles["Small"])],
        [Paragraph("P1", styles["SmallBold"]), Paragraph("Introduccion y resultados", styles["Small"]), Paragraph("Presentar desde el inicio las tres corrientes y explicar que IP + IL no es la corriente de enlace IN,1.", styles["Small"])],
        [Paragraph("P1", styles["SmallBold"]), Paragraph("Sec. V y Fig. 6", styles["Small"]), Paragraph("Matizar la lectura de Rashba como flujo efectivo: para acoplamiento finito conviene formular la fase como estructura SU(2).", styles["Small"])],
        [Paragraph("P2", styles["SmallBold"]), Paragraph("Figuras y PDF", styles["Small"]), Paragraph("Eliminar motor barrido_IR, quitar recuadros rojos de hyperref, ampliar fuentes y reflujo de la Fig. 6 para evitar la pagina casi vacia.", styles["Small"])],
    ]
    table = Table(rows, colWidths=[60, 110, 346], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#243447")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#AAB7C4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F7F9FB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(PageBreak())
    story.append(Paragraph("Texto revisado sugerido", styles["TitleCenter"]))
    story.append(Paragraph("Resumen - version propuesta", styles["H2Custom"]))
    story.append(Paragraph(
        "Estudiamos un anillo mesoscopico de Aharonov-Bohm de N = 8 sitios con acoplamiento espin-orbita de Rashba, conectado a dos reservorios metalicos no interactuantes. Usamos funciones de Green retardada y menor en la aproximacion de banda ancha para calcular, dentro de un mismo formalismo, la corriente persistente de equilibrio, la corriente de transporte y la corriente de enlace fuera del equilibrio. En el modelo bipartito publicado, el espectro mantiene simetria respecto de cero y, a medio llenado, mu_eq = 0; el acoplamiento Rashba modifica la brecha central y la distribucion espectral, pero no desplaza ese punto medio. Para la configuracion de referencia, Rashba produce interferencia tipo Aharonov-Bohm/Aharonov-Casher en la transmision y una dependencia no monotona de la amplitud de la corriente persistente, con un minimo alrededor de lambda_R = 0.48 |gamma|. La corriente de enlace a voltaje finito puede diferir sustancialmente de su valor de equilibrio. El umbral Gamma* reportado debe interpretarse como un benchmark dependiente de las condiciones elegidas para comparar las amplitudes, no como una constante universal del sistema.",
        styles["Small"],
    ))
    story.append(Paragraph("Parrafo sustitutivo para la Sec. VII.A", styles["H2Custom"]))
    story.append(Paragraph(
        "El Hamiltoniano del anillo conecta solamente subredes alternas. Por ello anticommuta con el operador quiral C = sum_n (-1)^n P_n tensor I_spin, donde P_n es el proyector sobre el sitio n, y sus autovalores aparecen en pares E y -E. Para N = 8 y N_e = 8, el potencial quimico de medio llenado es, por tanto, mu_eq = 0 dentro de la precision numerica para todo flujo y todo lambda_R. El acoplamiento Rashba levanta y reorganiza degeneraciones, modifica la separacion entre los niveles centrales y cambia la identidad de los estados ocupados, pero no desplaza el punto medio. La implementacion 4N debe demostrar explicitamente que es una duplicacion fiel de la matriz fisica 2N y que no altera la normalizacion de las observables.",
        styles["Small"],
    ))
    story.append(Paragraph("Parrafo sustitutivo para la Sec. VII.F", styles["H2Custom"]))
    story.append(Paragraph(
        "Definimos Gamma* como el valor del acoplamiento para el cual max_phi |IP| coincide con la corriente de Landauer evaluada en el protocolo de referencia, phi = 0.5 phi_0 y eV = 2 |gamma|. Esta definicion permite comparar dos escalas caracteristicas, pero no establece una frontera universal entre equilibrio y transporte: el resultado depende del voltaje, del flujo escogido, del llenado y de si las dos amplitudes se optimizan con el mismo criterio.",
        styles["Small"],
    ))
    story.append(PageBreak())
    story.append(Paragraph("Conclusiones - version propuesta", styles["TitleCenter"]))
    story.append(Paragraph(
        "El anillo abierto estudiado permite calcular de forma consistente tres magnitudes diferentes: la corriente persistente de equilibrio, la corriente de transporte entre reservorios y la corriente de enlace fuera del equilibrio. El acoplamiento Rashba redistribuye el peso espectral, modula la transmision y produce una respuesta no monotona de la corriente persistente. La corriente de enlace puede invertirse o perder la antisimetria simple en el flujo cuando se aplica una diferencia de potencial, aunque conserva la simetria de reflexion especificada en el manuscrito.",
        styles["Small"],
    ))
    story.append(Paragraph(
        "En el modelo nearest-neighbor, par y sin terminos onsite, la simetria quiral fija mu_eq = 0 a medio llenado. Esta propiedad debe incorporarse a la interpretacion del espectro y verificarse directamente en el codigo. Las comparaciones entre corriente persistente y corriente de Landauer son benchmarks bajo un protocolo definido; no deben interpretarse como la suma de dos contribuciones a una unica corriente ni como una ley universal independiente de las condiciones de operacion.",
        styles["Small"],
    ))
    story.append(Paragraph("Checklist antes de envio", styles["H2Custom"]))
    checklist = [
        "Mostrar la matriz 4N y su relacion exacta con la matriz fisica 2N.",
        "Verificar numericamente C H C + H = 0 y la simetria E <-> -E.",
        "Aclarar si mu_eq se mantiene fijo o se recalcula con flujo y parametros.",
        "Reportar errores de malla, limites WBA y procedimiento de eta -> 0.",
        "Depositar codigo y datos de las figuras.",
        "Actualizar la bibliografia y cuantificar el ajuste Fano.",
    ]
    for item in checklist:
        story.append(Paragraph("- " + item, styles["Small"]))
    doc.build(story)
    return path


def build_email():
    body = """Asunto: Evaluacion y propuesta de revision del articulo sobre anillo Aharonov-Bohm-Rashba

Estimados autores:

He revisado el manuscrito sobre el anillo de Aharonov-Bohm con acoplamiento Rashba y reservorios metalicos, incluyendo su consistencia formal, narrativa, figuras y resultados numericos. La evaluacion general es positiva en cuanto al interes del problema y a la amplitud del estudio, pero considero necesaria una revision mayor antes de someterlo a publicacion.

Las principales fortalezas son el tratamiento conjunto de la corriente persistente, la corriente de transporte y la corriente de enlace fuera del equilibrio; el estudio de la dependencia no monotona con el acoplamiento Rashba; y las verificaciones de gauge, unitariedad, limite aislado y convergencia.

El punto mas importante que debe resolverse es la discusion del potencial quimico de medio llenado. Para el Hamiltoniano publicado, con N par y solamente hoppings entre primeros vecinos, existe una simetria quiral que fuerza el espectro a aparecer en pares E y -E. Por consiguiente, a medio llenado debe cumplirse mu_eq = 0 para todo flujo y todo acoplamiento Rashba. El texto afirma que mu_eq presenta saltos, mientras que la Fig. 4 parece mostrarlo constante. Es necesario corregir esa interpretacion o explicar que termino adicional del codigo rompe la simetria publicada.

Tambien recomiendo: documentar la representacion numerica 4N frente al espacio fisico 2N; presentar Gamma* como un benchmark dependiente del protocolo; evitar llamar dominante a una corriente comparada con otra magnitud que no se evalua bajo las mismas condiciones; aclarar que IP + IL no es la corriente de enlace; proporcionar codigo, datos, mallas y errores; y matizar la interpretacion del acoplamiento Rashba como flujo efectivo escalar.

Desde el punto de vista narrativo, conviene definir las tres corrientes en la introduccion, formular una pregunta central mas clara y reorganizar los resultados alrededor de espectro, transmision, corriente persistente y respuesta fuera del equilibrio. En la parte grafica deben eliminarse textos internos como "motor barrido_IR", quitar los recuadros de hyperref y mejorar el reflujo de la ultima figura.

Mi recomendacion es revision mayor, no rechazo. El manuscrito puede convertirse en una contribucion valiosa si se resuelve la inconsistencia de mu_eq y se acotan las conclusiones a las condiciones realmente estudiadas.

Adjunto una version marcada del PDF con los pasajes resaltados y un suplemento con texto revisado sugerido para el resumen, las secciones criticas y las conclusiones.

Saludos cordiales,
"""
    EMAIL.write_text(body, encoding="utf-8")


if __name__ == "__main__":
    build_marked_pdf()
    build_email()
    # Build the clean suggested-text supplement after the marked PDF exists.
    make_change_log_pdf().replace(SUPPLEMENT) if False else None
    temp = OUT / "_anillo_change_log.pdf"
    temp.replace(SUPPLEMENT)
    print(MARKED)
    print(SUPPLEMENT)
    print(EMAIL)
