--[[--
Periódico: descarga portada.png desde el computador (periodico.py)
y la deja como pantalla de suspensión de KOReader.
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

local function avisar(texto, segundos)
    UIManager:show(InfoMessage:new{ text = texto, timeout = segundos })
end

local function usarComoSuspension()
    G_reader_settings:saveSetting("screensaver_type", "document_cover")
    G_reader_settings:saveSetting("screensaver_document_cover", ARCHIVO)
end

-- Descarga la portada. Devuelve true si se actualizó.
function Periodico:descargar(silencioso)
    local direccion = url()
    if not direccion or direccion == "" then
        if not silencioso then
            avisar("Primero configura la dirección del computador.")
        end
        return false
    end

    local http = require("socket.http")
    local ltn12 = require("ltn12")
    local socket = require("socket")
    local socketutil = require("socketutil")

    local partes = {}
    socketutil:set_timeout(10, 30)
    local ok, code = pcall(function()
        return socket.skip(1, http.request{
            url = direccion,
            sink = ltn12.sink.table(partes),
        })
    end)
    socketutil:reset_timeout()

    local datos = table.concat(partes)
    -- Un PNG válido empieza con estos bytes; así nunca se guarda una página de error.
    if not ok or code ~= 200 or datos:sub(2, 4) ~= "PNG" then
        logger.warn("Periodico: descarga fallida", ok, code)
        if not silencioso then
            avisar("No se pudo descargar la portada.\n¿Está encendido el computador con periodico.py abierto y en el mismo Wi-Fi?")
        end
        return false
    end

    lfs.mkdir(CARPETA)
    local tmp = ARCHIVO .. ".tmp"
    local f = io.open(tmp, "wb")
    if not f then
        if not silencioso then avisar("No se pudo guardar la portada.") end
        return false
    end
    f:write(datos)
    f:close()
    os.rename(tmp, ARCHIVO)

    G_reader_settings:saveSetting("periodico_ultima", os.time())
    if not silencioso then
        avisar("Periódico actualizado.", 2)
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

function Periodico:pedirDireccion()
    local dialogo
    dialogo = InputDialog:new{
        title = "Dirección del periódico",
        description = "La que muestra periodico.py al iniciar, por ejemplo:\nhttp://192.168.1.100:8080/portada.png",
        input = url() or "http://192.168.1.",
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
                text = "Actualizar ahora",
                callback = function()
                    NetworkMgr:runWhenConnected(function()
                        avisar("Descargando…", 1)
                        UIManager:scheduleIn(1, function() self:descargar(false) end)
                    end)
                end,
            },
            {
                text = "Usar como pantalla de suspensión",
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
