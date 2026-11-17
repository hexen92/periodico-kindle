--[[--
Periódico: descarga la portada (portada.png) y el libro del día (periodico.epub).
La portada se usa como pantalla de suspensión; el libro queda en la carpeta
"Periodico" de tu biblioteca, con un capítulo por sección.
--]]--

local DataStorage = require("datastorage")
local InfoMessage = require("ui/widget/infomessage")
local InputDialog = require("ui/widget/inputdialog")
local NetworkMgr = require("ui/network/manager")
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")

local CARPETA = DataStorage:getDataDir() .. "/periodico"
local ARCHIVO = CARPETA .. "/portada.png"
local HORAS_ENTRE_DESCARGAS = 3
local LIBROS_A_GUARDAR = 4

local Periodico = WidgetContainer:extend{
    name = "periodico",
    is_doc_only = false,
}

function Periodico:init()
    self.ui.menu:registerToMainMenu(self)
end

local function url()
    return G_reader_settings:readSetting("periodico_url")
end

local function urlLibro()
    local u = url()
    if not u then return nil end
    return (u:gsub("portada%.png$", "periodico.epub"))
end

local function libroActivado()
    return G_reader_settings:nilOrTrue("periodico_libro")
end

local function avisar(texto, segundos)
    UIManager:show(InfoMessage:new{ text = texto, timeout = segundos })
end

local function usarComoSuspension()
    G_reader_settings:saveSetting("screensaver_type", "document_cover")
    G_reader_settings:saveSetting("screensaver_document_cover", ARCHIVO)
end

local function carpetaLibros()
    local ok, fmu = pcall(require, "apps/filemanager/filemanagerutil")
    local home = ok and fmu.getHomeFolder and fmu.getHomeFolder() or nil
    if not home or home == "." then home = "/mnt/us/documents" end
    return home .. "/Periodico"
end

-- Descarga una dirección completa en memoria. Devuelve los datos o nil.
local function bajar(direccion, segundos)
    local http = require("socket.http")
    local ltn12 = require("ltn12")
    local socket = require("socket")
    local socketutil = require("socketutil")

    local partes = {}
    socketutil:set_timeout(15, segundos or 30)
    local ok, code = pcall(function()
        return socket.skip(1, http.request{
            url = direccion,
            sink = ltn12.sink.table(partes),
        })
    end)
    socketutil:reset_timeout()
    if not ok or code ~= 200 then
        logger.warn("Periodico: descarga fallida", direccion, ok, code)
        return nil
    end
    return table.concat(partes)
end

local function guardar(ruta, datos)
    local tmp = ruta .. ".tmp"
    local f = io.open(tmp, "wb")
    if not f then return false end
    f:write(datos)
    f:close()
    return os.rename(tmp, ruta)
end

-- Lista los libros del periódico, del más nuevo al más viejo.
local function librosGuardados()
    local carpeta = carpetaLibros()
    local lista = {}
    if lfs.attributes(carpeta, "mode") ~= "directory" then return lista end
    for nombre in lfs.dir(carpeta) do
        if nombre:match("^Periodico .*%.epub$") then
            table.insert(lista, carpeta .. "/" .. nombre)
        end
    end
    table.sort(lista, function(a, b) return a > b end)
    return lista
end

function Periodico:libroAbierto()
    return self.ui and self.ui.document and self.ui.document.file
end

-- Borra los libros más viejos (y sus datos de lectura), nunca el que está abierto.
function Periodico:limpiarViejos()
    local abierto = self:libroAbierto()
    for i, ruta in ipairs(librosGuardados()) do
        if i > LIBROS_A_GUARDAR and ruta ~= abierto then
            os.remove(ruta)
            local sdr = ruta:gsub("%.epub$", ".sdr")
            if lfs.attributes(sdr, "mode") == "directory" then
                pcall(function() require("ffi/util").purgeDir(sdr) end)
            end
        end
    end
end

function Periodico:descargarLibro()
    local datos = bajar(urlLibro(), 90)
    if not datos or datos:sub(1, 2) ~= "PK" then  -- un EPUB es un ZIP: empieza con "PK"
        return false
    end
    local carpeta = carpetaLibros()
    lfs.mkdir(carpeta)
    local edicion = tonumber(os.date("%H")) < 14 and "manana" or "tarde"
    local ruta = string.format("%s/Periodico %s %s.epub", carpeta, os.date("%Y-%m-%d"), edicion)
    if ruta == self:libroAbierto() then
        return true  -- lo estás leyendo: no se reemplaza mientras está abierto
    end
    if not guardar(ruta, datos) then return false end
    self:limpiarViejos()
    return true
end

-- Descarga portada y libro. Devuelve true si se actualizó la portada.
function Periodico:descargar(silencioso)
    local direccion = url()
    if not direccion or direccion == "" then
        if not silencioso then
            avisar("Primero configura la dirección del periódico.")
        end
        return false
    end

    local datos = bajar(direccion, 30)
    -- Un PNG válido empieza con estos bytes; así nunca se guarda una página de error.
    if not datos or datos:sub(2, 4) ~= "PNG" then
        if not silencioso then
            avisar("No se pudo descargar la portada.\nRevisa el Wi-Fi y la dirección del periódico.")
        end
        return false
    end
    lfs.mkdir(CARPETA)
    if not guardar(ARCHIVO, datos) then
        if not silencioso then avisar("No se pudo guardar la portada.") end
        return false
    end
    G_reader_settings:saveSetting("periodico_ultima", os.time())

    local mensaje = "Portada actualizada."
    if libroActivado() then
        if self:descargarLibro() then
            mensaje = "Portada y libro actualizados."
        else
            mensaje = "Portada actualizada.\nEl libro no se pudo descargar."
        end
    end
    if not silencioso then
        avisar(mensaje, 3)
    end
    return true
end

function Periodico:necesitaActualizar()
    local ultima = G_reader_settings:readSetting("periodico_ultima") or 0
    return url() and os.time() - ultima > HORAS_ENTRE_DESCARGAS * 3600
end

-- Automático: al despertar o al conectarse al Wi-Fi, si ya pasaron unas horas.
function Periodico:intentarEnSegundoPlano()
    if not self:necesitaActualizar() then return end
    if not NetworkMgr:isConnected() then return end
    UIManager:scheduleIn(3, function() self:descargar(true) end)
end

function Periodico:onResume()
    self:intentarEnSegundoPlano()
end

function Periodico:onNetworkConnected()
    self:intentarEnSegundoPlano()
end

function Periodico:abrirLibro()
    local ruta = librosGuardados()[1]
    if not ruta then
        avisar("Todavía no hay libro. Usa «Actualizar ahora».")
        return
    end
    local ReaderUI = require("apps/reader/readerui")
    ReaderUI:showReader(ruta)
end

function Periodico:pedirDireccion()
    local dialogo
    dialogo = InputDialog:new{
        title = "Dirección del periódico",
        description = "Por ejemplo:\nhttps://usuario.github.io/periodico-kindle/portada.png",
        input = url() or "https://",
        buttons = {{
            {
                text = "Cancelar",
                id = "close",
                callback = function() UIManager:close(dialogo) end,
            },
            {
                text = "Guardar",
                is_enter_default = true,
                callback = function()
                    local texto = dialogo:getInputText():gsub("^%s+", ""):gsub("%s+$", "")
                    G_reader_settings:saveSetting("periodico_url", texto)
                    UIManager:close(dialogo)
                    avisar("Dirección guardada. Ahora usa «Actualizar ahora».", 3)
                end,
            },
        }},
    }
    UIManager:show(dialogo)
    dialogo:onShowKeyboard()
end

function Periodico:addToMainMenu(menu_items)
    menu_items.periodico = {
        text = "Periódico",
        sorting_hint = "tools",
        sub_item_table = {
            {
                text = "Abrir el periódico (libro)",
                enabled_func = function() return libroActivado() end,
                callback = function() self:abrirLibro() end,
            },
            {
                text = "Actualizar ahora",
                callback = function()
                    NetworkMgr:runWhenConnected(function()
                        avisar("Descargando…", 1)
                        UIManager:scheduleIn(1, function() self:descargar(false) end)
                    end)
                end,
                separator = true,
            },
            {
                text = "Usar portada como pantalla de suspensión",
                checked_func = function()
                    return G_reader_settings:readSetting("screensaver_type") == "document_cover"
                        and G_reader_settings:readSetting("screensaver_document_cover") == ARCHIVO
                end,
                callback = function()
                    if lfs.attributes(ARCHIVO, "mode") ~= "file" then
                        avisar("Primero descarga la portada con «Actualizar ahora».")
                        return
                    end
                    usarComoSuspension()
                    avisar("Listo: al bloquear el Kindle se verá el periódico.", 3)
                end,
            },
            {
                text = "Descargar también el libro",
                checked_func = function() return libroActivado() end,
                callback = function()
                    G_reader_settings:saveSetting("periodico_libro", not libroActivado())
                end,
            },
            {
                text_func = function()
                    return "Dirección: " .. (url() or "sin configurar")
                end,
                keep_menu_open = true,
                callback = function() self:pedirDireccion() end,
            },
        },
    }
end

return Periodico
