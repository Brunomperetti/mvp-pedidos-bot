from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Literal, Optional
import json
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import uuid
import os
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# ─────────────────────────────────────────────
# CONFIGURACIÓN FASTAPI
# ─────────────────────────────────────────────
app = FastAPI(
    title="MVP Pedidos Bot",
    description="Chatbot con carrito y PDF multi-item",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir front y admin
app.mount("/front", StaticFiles(directory="static_front", html=True), name="front")
app.mount("/admin", StaticFiles(directory="admin", html=True), name="admin")

# ─────────────────────────────────────────────
# CREAR CARPETA PDF (FIX PARA RENDER)
# ─────────────────────────────────────────────
if not os.path.exists("pedidos_pdf"):
    os.makedirs("pedidos_pdf")

# ─────────────────────────────────────────────
# CARGAR PRODUCTOS
# ─────────────────────────────────────────────
with open("productos.json", "r", encoding="utf-8") as f:
    PRODUCTOS = json.load(f)

# Sesiones con carrito
SESSIONS = {}  # { session_id: { "carrito": [], "producto": {...} } }

def buscar_producto(query: str):
    query = query.lower()
    for p in PRODUCTOS:
        if query in p["codigo"].lower() or query in p["nombre"].lower():
            return p
    return None

# ─────────────────────────────────────────────
# GENERAR PDF MULTI-ITEM
# ─────────────────────────────────────────────
def generar_pdf_carrito(carrito, session_id):

    pedido_id = str(uuid.uuid4())[:8]
    filename = f"pedido_{pedido_id}.pdf"
    file_path = os.path.join("pedidos_pdf", filename)

    c = canvas.Canvas(file_path, pagesize=letter)
    width, height = letter

    # Título
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, height - 50, "Pedido del Cliente")

    # Info
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 80, f"Pedido ID: {pedido_id}")
    c.drawString(50, height - 100, f"Sesión: {session_id}")

    # Tabla
    y = height - 150
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Cant.")
    c.drawString(110, y, "Producto")
    c.drawString(350, y, "Precio U.")
    c.drawString(430, y, "Total")
    y -= 20
    c.line(50, y, 550, y)
    y -= 20

    total_general = 0
    c.setFont("Helvetica", 11)

    for item in carrito:
        if y < 80:
            c.showPage()
            y = height - 80

        c.drawString(50, y, str(item["cantidad"]))
        c.drawString(110, y, item["nombre"])
        c.drawString(350, y, f"${item['precio']}")
        c.drawString(430, y, f"${item['total']}")

        total_general += item["total"]
        y -= 20

    # Total final
    y -= 20
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, f"TOTAL GENERAL: ${total_general}")

    c.save()
    return filename

# ─────────────────────────────────────────────
# MODELO DE MENSAJE
# ─────────────────────────────────────────────
class ChatMessage(BaseModel):
    session_id: str
    text: str
    stage: Optional[Literal[
        "inicio",
        "esperando_producto",
        "esperando_cantidad",
        "preguntar_otro",
        "finalizar",
        "confirmacion"
    ]] = "inicio"


# ─────────────────────────────────────────────
# PANEL ADMIN
# ─────────────────────────────────────────────
@app.get("/productos")
def obtener_productos():
    return PRODUCTOS

@app.post("/crear_producto")
def crear_producto(data: dict):
    nuevo = {
        "codigo": data["codigo"],
        "nombre": data["nombre"],
        "precio": int(data["precio"]),
        "stock_color": data["stock_color"]
    }

    for p in PRODUCTOS:
        if p["codigo"] == nuevo["codigo"]:
            return {"status": "error", "message": "Código ya existe"}

    PRODUCTOS.append(nuevo)

    with open("productos.json", "w", encoding="utf-8") as f:
        json.dump(PRODUCTOS, f, indent=4, ensure_ascii=False)

    return {"status": "ok"}

@app.post("/actualizar_producto")
def actualizar_producto(data: dict):
    codigo = data["codigo"]

    for p in PRODUCTOS:
        if p["codigo"] == codigo:
            p["nombre"] = data["nombre"]
            p["precio"] = int(data["precio"])
            p["stock_color"] = data["stock_color"]

            with open("productos.json", "w", encoding="utf-8") as f:
                json.dump(PRODUCTOS, f, indent=4, ensure_ascii=False)

            return {"status": "ok"}

    return {"status": "error", "message": "No encontrado"}


# ─────────────────────────────────────────────
# CHATBOT COMPLETO (CARRITO + PDF)
# ─────────────────────────────────────────────
@app.post("/chat")
def chat(message: ChatMessage):

    user_text = message.text.strip().lower()
    stage = message.stage

    # INICIO
    if stage == "inicio":
        respuesta = (
            "👋 Hola! Soy el asistente automático.\n"
            "Decime el *código o nombre* del producto."
        )
        next_stage = "esperando_producto"

    # BUSCAR PRODUCTO
    elif stage == "esperando_producto":

        producto = buscar_producto(user_text)

        if not producto:
            respuesta = "❌ No encontré ese producto. Probá con otra palabra."
            next_stage = "esperando_producto"

        else:
            if message.session_id not in SESSIONS:
                SESSIONS[message.session_id] = {"carrito": [], "producto": producto}
            else:
                SESSIONS[message.session_id]["producto"] = producto

            respuesta = (
                f"🛒 *{producto['nombre']}*\n"
                f"Precio: ${producto['precio']}\n\n"
                "¿Cuántas unidades?"
            )
            next_stage = "esperando_cantidad"

    # CANTIDAD → agregar al carrito
    elif stage == "esperando_cantidad":

        producto = SESSIONS[message.session_id]["producto"]
        cantidad = int(user_text)

        SESSIONS[message.session_id]["carrito"].append({
            "codigo": producto["codigo"],
            "nombre": producto["nombre"],
            "precio": producto["precio"],
            "cantidad": cantidad,
            "total": producto["precio"] * cantidad
        })

        respuesta = (
            f"🛒 Agregué *{cantidad}x {producto['nombre']}* al carrito.\n\n"
            "¿Querés agregar otro producto? (si / no)"
        )
        next_stage = "preguntar_otro"

    # PREGUNTAR SI AGREGA MÁS
    elif stage == "preguntar_otro":

        if user_text in ["si", "sí", "s", "dale"]:
            respuesta = "Perfecto 🙌\nDecime el código o nombre del próximo producto."
            next_stage = "esperando_producto"

        elif user_text in ["no", "n", "listo"]:
            respuesta = "Perfecto 👌\nGenerando el resumen..."
            next_stage = "finalizar"

        else:
            respuesta = "No entendí 😅 ¿Agregamos otro? (si / no)"
            next_stage = "preguntar_otro"

    # MOSTRAR RESUMEN
    elif stage == "finalizar":

        carrito = SESSIONS[message.session_id]["carrito"]

        if not carrito:
            respuesta = "Tu carrito está vacío 😕. Empecemos de nuevo."
            next_stage = "inicio"

        else:
            respuesta = "🧾 *Resumen del pedido:*\n\n"
            total_general = 0

            for item in carrito:
                respuesta += (
                    f"- {item['cantidad']}x {item['nombre']} "
                    f"(${item['precio']} c/u) = ${item['total']}\n"
                )
                total_general += item["total"]

            respuesta += f"\n💰 *Total: ${total_general}*\n\n"
            respuesta += "¿Querés que genere el PDF? (si / no)"

            next_stage = "confirmacion"

    # GENERAR PDF
    elif stage == "confirmacion":

        if user_text in ["si", "sí", "s", "dale"]:
            carrito = SESSIONS[message.session_id]["carrito"]

            pdf_filename = generar_pdf_carrito(carrito, message.session_id)

            # FIX PARA RENDER → URL RELATIVA
            pdf_url = f"/pdf/{pdf_filename}"

            respuesta = (
                "📄 Tu PDF está listo!\n"
                f"{pdf_url}\n\n"
                "Gracias por usar el asistente 🙌"
            )

            next_stage = "inicio"

        else:
            respuesta = "Perfecto 👍 Pedido cancelado."
            next_stage = "inicio"

    else:
        respuesta = "No entendí 🔁. Decime un producto."
        next_stage = "esperando_producto"

    return {"reply": respuesta, "next_stage": next_stage}


# ─────────────────────────────────────────────
# SERVIR PDF (CORRECTO PARA RENDER)
# ─────────────────────────────────────────────
@app.get("/pdf/{filename}")
def get_pdf(filename: str):
    filepath = os.path.join("pedidos_pdf", filename)
    return FileResponse(filepath, media_type="application/pdf", filename=filename)
