# CityCrawl 🛣️

**Detecta, prioriza y optimiza la reparación de infraestructura urbana — combinando video a nivel calle, visión por computadora y datos de riesgo.**

🏙️ Platanus Hack 26: CDMX · Track ☎️ Legacy

> 🔗 [citycrawl.dev](https://citycrawl.dev) · usuario de prueba `tester@citycrawl.dev` / `Test1234!`

---

## El problema

Las ciudades reparan su infraestructura **a ciegas**. Baches, coladeras abiertas, luminarias dañadas y señalización faltante se atienden por reportes ciudadanos dispersos, sin una visión real de **dónde** están los problemas, **cuáles** son más peligrosos, ni **cómo** gastar el presupuesto para que rinda más.

El resultado: dinero público mal invertido, zonas de riesgo ignoradas y reparaciones que no priorizan a quienes más las necesitan.

## La solución

**CityCrawl** cierra ese ciclo de principio a fin — de la cámara en la calle a la decisión de gasto — y se opera **en lenguaje natural**.

### 1. 📹 Captura georreferenciada
Toma video a nivel calle desde cámaras en rutas o **montadas en flotas que ya recorren la ciudad** (camiones de basura, transporte). Sin infraestructura nueva: aprovecha lo que ya se mueve. Los recordings se almacenan en Cloudflare R2 y se sirven bajo autorización por inquilino.

### 2. 👁️ Detección con visión por computadora
Modelos de visión identifican y ubican problemas de infraestructura — **baches, coladeras abiertas, luminarias dañadas, señalización faltante** — y los convierten en *observaciones* georreferenciadas, cada una con su evidencia (frame) trazable.

### 3. 🗺️ Mapa de prioridad por riesgo
Cruza las detecciones con **señales externas de riesgo** — accidentes viales (SSC *Hechos de tránsito*) y criminalidad (FGJ *Carpetas de investigación*) — ancladas a la geografía oficial **INEGI Marco Geoestadístico** (AGEE → AGEM → AGEB). El mapa no solo muestra *qué* está roto, sino *qué tan urgente* es, en capas de instancias y de calor.

### 4. 🔍 Descubrimiento de problemas latentes
A partir del mapa de riesgo, identifica **zonas de alto riesgo sin reportes** y ejecuta un **VLM** sobre el video de esas regiones de interés para descubrir problemas que nadie había reportado todavía.

### 5. 💰 Optimización del gasto público
Dado un **presupuesto**, selecciona qué reparar para **maximizar el impacto por peso invertido**. El pipeline agrupa baches por calle en *clusters* y *superclusters*, estima el flujo vehicular con la **API de tráfico de TomTom**, y selecciona de forma voraz las zonas de mayor impacto que caben en el presupuesto. Minimiza el "descontento" poblacional, modelado como:

> **velocidad de la vía × flujo vehicular semanal × volumen del bache**

Así, cada peso se asigna donde más alivia a la población. El resultado se devuelve como rutas óptimas de servicio y clusters de máximo impacto, dibujados directamente sobre el mapa.

## ☎️ Track Legacy: todo en lenguaje natural

CityCrawl se opera por **canales legacy**, sin curva técnica:

- **Lenguaje natural** → cualquier funcionario escribe *"mejor ruta en Gustavo A. Madero con 3 millones de presupuesto"* y el sistema lo resuelve contra el catálogo INEGI en un borrador editable, listo para ejecutar.
- **Reportes ciudadanos por WhatsApp** → un ciudadano manda una **foto** + un **pin de ubicación** y eso se convierte automáticamente en una observación en el mapa (integración vía Kapso).

## 🏗️ Arquitectura

| Componente | Stack |
|---|---|
| **Web app** — mapa de prioridad, capas de calor, borradores y resultados | Vite + React + Tailwind, Cloudflare Pages |
| **API** — planning/optimización, parseo de lenguaje natural (Anthropic), datasets | FastAPI (monolito modular) en Fly.io |
| **Optimización accionable** — clustering, tráfico, selección por presupuesto | Python + TomTom Traffic API |
| **Broker de medios** — sirve bytes de R2 con autorización por inquilino | Cloudflare Worker |
| **Datos & auth** — observaciones, prioridades, geografía, RLS | Supabase (PostgreSQL/PostGIS) |
| **Controlador WhatsApp** — reportes ciudadanos foto + pin | Node/TS + Kapso |

Diseño guiado por contratos versionados y *runs* reproducibles: cada análisis congela sus insumos (geografía, observaciones, presupuesto, versión de proveedor) para ser **explicable y repetible** aunque los datos en vivo cambien.

---

## El equipo — team-21

- Pablo César Ruíz Hernández ([@pcruiher08](https://github.com/pcruiher08))
- Elias Garza Valdes ([@eliasgarzav](https://github.com/eliasgarzav))
- Andrés Alam Sánchez Torres ([@aast12](https://github.com/aast12))
- Sofia Ingigerth Cañas Urbina ([@sicupath](https://github.com/sicupath))
- Roberto Mendivil ([@robertomendivil97](https://github.com/robertomendivil97))
