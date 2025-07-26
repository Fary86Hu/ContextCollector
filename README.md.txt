# LLM Context Collector v8.0

Egy asztali alkalmazás Windows-ra, ami segít gyorsan és hatékonyan összegyűjteni és formázni kódrészleteket és fájlokat, hogy tiszta, másolható kontextust biztosítson Nagy Nyelvi Modellek (LLM-ek), mint a ChatGPT, Gemini vagy a Claude számára.

<!-- 
    IDE ILLESSZ BE EGY KÉPERNYŐKÉPET AZ ALKALMAZÁSRÓL! 
    Készíts egy képet a futó programról, mentsd el a projekt mappájába pl. `screenshot.png` néven,
    majd a következő sort cseréld ki erre: ![App Screenshot](screenshot.png)
-->
![App Screenshot](URL_A_KEPERNYOKEPHEZ)

## Probléma és Megoldás

Fejlesztőként gyakran kell több fájl tartalmát egy LLM-nek átadni. Ez a folyamat általában manuális másolgatásból, formázásból és a felesleges részek eltávolításából áll. Ez az eszköz automatizálja ezt:

*   **Szkenneli** a projektmappádat a megadott kiterjesztések és ignore-szabályok alapján.
*   **Összegyűjti** a kiválasztott fájlokat egyetlen, rendezett szöveggé.
*   **Formázza** a kimenetet, hogy az LLM-ek számára könnyen értelmezhető legyen.
*   **Kezeli** az LLM-től kapott kód-változtatásokat egy beépített "diff" eszköz segítségével.

## Főbb Funkciók

*   **Projektkezelés:** Tallózz be egy projektmappát, és az eszköz rekurzívan feltérképezi a fájlstruktúrát.
*   **Részletes Szűrés:**
    *   Szűrés fájlkiterjesztésekre (pl. `.cs, .py, .js`).
    *   Mappák és fájlok kizárása `.gitignore`-szerű mintákkal.
*   **Egyesített Keresés:**
    *   Keress fájlnevekre és mappanevekre a gyors szűréshez.
    *   **Tartalmi keresés:** Opcionálisan keress a fájlok tartalmában is a releváns referenciákért. A csak tartalmi egyezés alapján talált fájlok `[REF]` előtagot kapnak.
*   **Kontextus Menedzsment:**
    *   Fájlokat és mappákat adhatsz a kontextus listához. Szűrt nézetben a mappák hozzáadásakor csak a látható fájlok kerülnek a listára.
    *   Visszavonás/Ismétlés funkció a lista módosításaihoz.
*   **Változások Kezelése Vágólapról:**
    *   Másold ki az LLM által generált teljes választ a vágólapra.
    *   Az eszköz automatikusan elemzi a választ, szétválasztja a magyarázatot és a kódrészleteket.
    *   Egy beépített diff nézetben mutatja a változásokat (új, módosított fájlok), amiket egy gombnyomással elfogadhatsz és beírhatsz a helyi fájlokba.
*   **Prompt Sablonok:** Hozz létre és ments el gyakran használt promptokat, hogy ne kelljen őket újra és újra begépelni.
*   **Hasznos Információk:** Az eszköz folyamatosan mutatja a gyűjtött kontextus karaktereinek és becsült tokenjeinek számát.
*   **Előzmények:** Automatikusan elmenti a legutóbbi munkameneteket (mappa, filterek, kiválasztott fájlok), hogy gyorsan folytathasd a munkát.

## Használat

### Végfelhasználóknak (ajánlott)

A legegyszerűbb módja az alkalmazás használatának, ha letöltöd az előre elkészített `.exe` fájlt.

1.  Menj a projekt [**Releases**](<!-- IDE ILLESSZ BE A GITHUB REPOZITÓRIUMOD LINKJÉT, PL. https://github.com/felhasznalonev/repo/releases -->) oldalára.
2.  Töltsd le a legfrissebb `LLM_Context_Collector.exe` fájlt.
3.  Indítsd el a fájlt. Nincs szükség telepítésre.

### Fejlesztőknek (futtatás forráskódból)

Ha módosítani szeretnéd a kódot vagy hibát keresel, a forráskódból is futtathatod.

**Előfeltételek:**
*   Python 3.12 (A `tkinter` hibátlan működése miatt ez a javasolt verzió.)
*   Git

**Lépések:**
1.  Klónozd a repozitóriumot:
    ```bash
    git clone <!-- IDE ILLESSZ BE A REPOZITÓRIUMOD KLÓNOZÁSI URL-JÉT -->
    cd <repozitorium-neve>
    ```

2.  Hoz létre és aktiválj egy virtuális környezetet:
    ```bash
    # Windows
    python -m venv .venv
    .venv\Scripts\activate
    ```

3.  Telepítsd a szükséges függőségeket:
    ```bash
    pip install gitignore-parser
    ```

4.  Futasd az alkalmazást:
    ```bash
    python llm-context-collector.py
    ```

## .exe Fájl Létrehozása a Forráskódból

Ha saját magad szeretnéd elkészíteni a futtatható `.exe` fájlt, kövesd az alábbi lépéseket a fejlesztői környezet beállítása után.

1.  Telepítsd a PyInstaller-t:
    ```bash
    pip install pyinstaller
    ```

2.  (Opcionális) Helyezz el egy `icon.ico` nevű ikonfájlt a projekt gyökérmappájába az egyedi ikonhoz.

3.  Futtasd a PyInstaller parancsot a projekt gyökérmappájából:
    ```bash
    pyinstaller --onefile --windowed --name "LLM Context Collector" --icon="icon.ico" llm-context-collector.py
    ```
    *   `--onefile`: Mindent egyetlen `.exe`-be csomagol.
    *   `--windowed`: Elrejti a felesleges parancssori ablakot a GUI alkalmazás mögül.

4.  Az elkészült futtatható fájl a `dist` mappában található meg.

## Felhasznált Technológiák

*   **Python 3.12**
*   **Tkinter** (a Python beépített GUI könyvtára)
*   **PyInstaller** (az `.exe` fájl készítéséhez)

## Hozzájárulás

Hibajelentéseket és funkciókéréseket szívesen fogadok! Kérlek, nyiss egy "Issue"-t a GitHub repozitóriumában.

## Licenc

Ez a projekt az MIT Licenc alatt áll. A részletekért olvasd el a `LICENSE` fájlt.