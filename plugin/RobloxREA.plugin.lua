-- ROBLOX-REA v0.1 | Studio plugin (not a LocalScript or executor script)
-- Purpose: document, back up and reconstruct maps in experiences you own or may edit.
-- All network calls are local to http://127.0.0.1:8787 and use a private token.
-- REA-RBX never reads other running Roblox clients or private server contents.

local HttpService = game:GetService("HttpService")
local Selection = game:GetService("Selection")
local ServerStorage = game:GetService("ServerStorage")
local SerializationService = game:GetService("SerializationService")

local API = "http://127.0.0.1:8787"
local MAX_NODES = 15000
local toolbar = plugin:CreateToolbar("ROBLOX-REA")
local toggle = toolbar:CreateButton("ROBLOX-REA", "Open map scanner and reconstruction tools", "")
local widgetInfo = DockWidgetPluginGuiInfo.new(Enum.InitialDockState.Float, false, false, 450, 570, 350, 420)
local widget = plugin:CreateDockWidgetPluginGui("ROBLOX_REA_v01", widgetInfo)
widget.Title = "ROBLOX-REA · Map Lab"

local function newGui(className, props, parent)
    local instance = Instance.new(className)
    for key, value in pairs(props or {}) do
        instance[key] = value
    end
    instance.Parent = parent
    return instance
end

local root = newGui("ScrollingFrame", {
    Size = UDim2.fromScale(1, 1),
    ScrollBarThickness = 6,
    CanvasSize = UDim2.new(0, 0, 0, 780),
    BackgroundColor3 = Color3.fromRGB(22, 26, 37),
    BorderSizePixel = 0,
}, widget)
local layout = newGui("UIListLayout", {
    FillDirection = Enum.FillDirection.Vertical,
    SortOrder = Enum.SortOrder.LayoutOrder,
    Padding = UDim.new(0, 9),
}, root)
newGui("UIPadding", {
    PaddingLeft = UDim.new(0, 15),
    PaddingRight = UDim.new(0, 15),
    PaddingTop = UDim.new(0, 13),
    PaddingBottom = UDim.new(0, 12),
}, root)

local function textLabel(text, height, color)
    return newGui("TextLabel", {
        Text = text,
        Font = Enum.Font.Gotham,
        TextSize = 13,
        TextWrapped = true,
        TextColor3 = color or Color3.fromRGB(220, 228, 240),
        BackgroundTransparency = 1,
        Size = UDim2.new(1, 0, 0, height),
        TextXAlignment = Enum.TextXAlignment.Left,
    }, root)
end

local function textInput(placeholder, height, password)
    local input = newGui("TextBox", {
        Text = "",
        PlaceholderText = placeholder,
        ClearTextOnFocus = false,
        Font = Enum.Font.Code,
        TextSize = 12,
        TextColor3 = Color3.fromRGB(245, 248, 255),
        PlaceholderColor3 = Color3.fromRGB(145, 153, 168),
        BackgroundColor3 = Color3.fromRGB(42, 49, 65),
        BorderSizePixel = 0,
        Size = UDim2.new(1, 0, 0, height),
        TextXAlignment = Enum.TextXAlignment.Left,
        TextTruncate = Enum.TextTruncate.AtEnd,
    }, root)
    newGui("UICorner", {CornerRadius = UDim.new(0, 7)}, input)
    newGui("UIPadding", {PaddingLeft = UDim.new(0, 9), PaddingRight = UDim.new(0, 9)}, input)
    -- Roblox TextBoxes do not expose password masking; users should keep the token private.
    return input
end

local function actionButton(label, callback)
    local button = newGui("TextButton", {
        Text = label,
        Font = Enum.Font.GothamBold,
        TextSize = 14,
        TextColor3 = Color3.fromRGB(255, 255, 255),
        BackgroundColor3 = Color3.fromRGB(55, 96, 173),
        BorderSizePixel = 0,
        Size = UDim2.new(1, 0, 0, 39),
        AutoButtonColor = true,
    }, root)
    newGui("UICorner", {CornerRadius = UDim.new(0, 7)}, button)
    button.MouseButton1Click:Connect(function()
        task.spawn(callback)
    end)
end

textLabel("ROBLOX-REA  ·  v0.1", 27, Color3.fromRGB(109, 173, 255)).TextSize = 19
textLabel("Select a Model or Folder in Explorer. Outputs go to your local Python bridge; restored models stay in ServerStorage for review.", 55)
textLabel("Bridge token (printed by: rea-rbx serve)", 20)
local tokenField = textInput("Paste the local token", 36, true)
local saved = plugin:GetSetting("REA_RBX_LOCAL_TOKEN")
if typeof(saved) == "string" then
    tokenField.Text = saved
end
tokenField.FocusLost:Connect(function()
    plugin:SetSetting("REA_RBX_LOCAL_TOKEN", tokenField.Text)
end)
textLabel("Capture ID (from JSON scan)", 20)
local captureField = textInput("Capture ID appears after scan", 36)
textLabel("Native model ID (from RBXM backup)", 20)
local nativeField = textInput("Native ID appears after backup", 36)
local status = textLabel("Ready. Select your own Studio map.", 58, Color3.fromRGB(180, 231, 198))

local function setStatus(message, isError)
    status.Text = tostring(message)
    status.TextColor3 = isError and Color3.fromRGB(255, 144, 144) or Color3.fromRGB(180, 231, 198)
end

local function request(method, path, body, contentType, headers)
    local token = tokenField.Text:gsub("^%s+", ""):gsub("%s+$", "")
    assert(#token == 64, "Start rea-rbx serve and paste its 64-character token")
    local requestHeaders = headers or {}
    requestHeaders["X-REA-Token"] = token
    if contentType then
        requestHeaders["Content-Type"] = contentType
    end
    local options = {
        Url = API .. path,
        Method = method,
        Headers = requestHeaders,
    }
    if body ~= nil then
        options.Body = body
    end
    local response = HttpService:RequestAsync(options)
    if not response.Success then
        local description = response.Body
        if #description > 240 then
            description = description:sub(1, 240)
        end
        error("Bridge HTTP " .. tostring(response.StatusCode) .. ": " .. description)
    end
    return response
end

local function selectedMap()
    local items = Selection:Get()
    assert(#items == 1, "Select exactly one Model, Folder, or BasePart")
    local item = items[1]
    assert(item:IsDescendantOf(workspace), "Selection must be inside your current Workspace")
    assert(not item:IsA("Terrain"), "Terrain voxels are not supported by this model exporter")
    assert(item:IsA("Model") or item:IsA("Folder") or item:IsA("BasePart"), "Select a Model, Folder, or BasePart")
    return item
end

local function vec3(v)
    return {v.X, v.Y, v.Z}
end

local function color3(v)
    return {v.R, v.G, v.B}
end

local function cframe(v)
    return {v:GetComponents()}
end

local function safeProperty(instance, name)
    local ok, value = pcall(function()
        return instance[name]
    end)
    return ok and value or nil
end

local function getProperties(instance)
    local p = {}
    if instance:IsA("BasePart") and not instance:IsA("Terrain") then
        p.size = vec3(instance.Size)
        p.cframe = cframe(instance.CFrame)
        p.color = color3(instance.Color)
        p.material = instance.Material.Name
        p.transparency = instance.Transparency
        p.reflectance = instance.Reflectance
        p.anchored = instance.Anchored
        p.can_collide = instance.CanCollide
        p.can_touch = instance.CanTouch
        p.can_query = instance.CanQuery
        p.cast_shadow = instance.CastShadow
        if instance:IsA("Part") then
            p.shape = instance.Shape.Name
        end
        if instance:IsA("MeshPart") then
            p.mesh_id = safeProperty(instance, "MeshId")
            p.texture_id = safeProperty(instance, "TextureID")
        end
    elseif instance:IsA("Decal") or instance:IsA("Texture") then
        p.texture = instance.Texture
        p.face = instance.Face.Name
        p.transparency = instance.Transparency
        p.color = color3(instance.Color3)
        if instance:IsA("Texture") then
            p.studs_per_tile_u = instance.StudsPerTileU
            p.studs_per_tile_v = instance.StudsPerTileV
        end
    elseif instance:IsA("SpecialMesh") then
        p.mesh_id = instance.MeshId
        p.texture_id = instance.TextureId
        p.mesh_type = instance.MeshType.Name
        p.scale = vec3(instance.Scale)
        p.offset = vec3(instance.Offset)
    elseif instance:IsA("Attachment") then
        p.local_cframe = cframe(instance.CFrame)
        p.visible = instance.Visible
    end
    return p
end

local function scanMap(source)
    local nodes = {}
    local stack = {{instance = source, parent_id = nil, path = "root"}}
    while #stack > 0 do
        local entry = table.remove(stack)
        assert(#nodes < MAX_NODES, "This capture exceeds the 15,000-node limit")
        local nextId = "n" .. tostring(#nodes + 1)
        local node = {
            id = nextId,
            parent_id = entry.parent_id,
            name = entry.instance.Name ~= "" and entry.instance.Name or "Unnamed",
            class = entry.instance.ClassName,
            path = entry.path,
            properties = getProperties(entry.instance),
        }
        table.insert(nodes, node)
        local children = entry.instance:GetChildren()
        local siblingCounts = {}
        local childrenWithPaths = {}
        for _, child in ipairs(children) do
            local label = child.ClassName .. ":" .. (child.Name ~= "" and child.Name or "Unnamed")
            siblingCounts[label] = (siblingCounts[label] or 0) + 1
            table.insert(childrenWithPaths, {
                instance = child,
                parent_id = nextId,
                path = entry.path .. "/" .. label .. "[" .. tostring(siblingCounts[label]) .. "]",
            })
        end
        for i = #childrenWithPaths, 1, -1 do
            table.insert(stack, childrenWithPaths[i])
        end
    end
    return {
        schema = "roblox-rea.scene.v1",
        scene_name = source.Name ~= "" and source.Name or "Unnamed",
        root_id = "n1",
        captured_at = os.time(),
        source = {kind = "studio-selection", place_id = game.PlaceId, root_class = source.ClassName},
        nodes = nodes,
    }
end

local function doAction(title, callback)
    setStatus(title .. "...", false)
    local ok, err = pcall(callback)
    if not ok then
        setStatus(err, true)
        warn("[ROBLOX-REA] " .. tostring(err))
    end
end

local function importFolder()
    local existing = ServerStorage:FindFirstChild("REA_Imports")
    if existing and existing:IsA("Folder") then
        return existing
    end
    assert(existing == nil, "ServerStorage.REA_Imports must be a Folder")
    local folder = Instance.new("Folder")
    folder.Name = "REA_Imports"
    folder.Parent = ServerStorage
    return folder
end

local ALLOWED = {
    Model = true, Folder = true, Part = true, WedgePart = true,
    CornerWedgePart = true, TrussPart = true, Seat = true, VehicleSeat = true,
    SpawnLocation = true, Decal = true, Texture = true, SpecialMesh = true,
    Attachment = true, MeshPart = true, UnionOperation = true,
}

local function reconstructNode(node)
    local className = node.class
    if not ALLOWED[className] then
        return nil, "unsupported class " .. tostring(className)
    end
    local placeholder = className == "MeshPart" or className == "UnionOperation"
    if placeholder then
        className = "Part"
    end
    local success, object = pcall(Instance.new, className)
    if not success then
        return nil, "cannot create " .. className
    end
    object.Name = node.name
    local p = node.properties or {}
    local function put(key, value)
        if value == nil then return end
        pcall(function() object[key] = value end)
    end
    if object:IsA("BasePart") then
        if p.size then put("Size", Vector3.new(table.unpack(p.size))) end
        if p.cframe then put("CFrame", CFrame.new(table.unpack(p.cframe))) end
        if p.color then put("Color", Color3.new(table.unpack(p.color))) end
        if p.material and Enum.Material[p.material] then put("Material", Enum.Material[p.material]) end
        put("Transparency", p.transparency)
        put("Reflectance", p.reflectance)
        put("Anchored", p.anchored)
        put("CanCollide", p.can_collide)
        put("CanTouch", p.can_touch)
        put("CanQuery", p.can_query)
        put("CastShadow", p.cast_shadow)
        if object:IsA("Part") and p.shape and Enum.PartType[p.shape] and not placeholder then
            put("Shape", Enum.PartType[p.shape])
        end
    elseif object:IsA("Decal") or object:IsA("Texture") then
        put("Texture", p.texture)
        put("Transparency", p.transparency)
        if p.face and Enum.NormalId[p.face] then put("Face", Enum.NormalId[p.face]) end
        if p.color then put("Color3", Color3.new(table.unpack(p.color))) end
        if object:IsA("Texture") then
            put("StudsPerTileU", p.studs_per_tile_u)
            put("StudsPerTileV", p.studs_per_tile_v)
        end
    elseif object:IsA("SpecialMesh") then
        put("MeshId", p.mesh_id)
        put("TextureId", p.texture_id)
        if p.mesh_type and Enum.MeshType[p.mesh_type] then put("MeshType", Enum.MeshType[p.mesh_type]) end
        if p.scale then put("Scale", Vector3.new(table.unpack(p.scale))) end
        if p.offset then put("Offset", Vector3.new(table.unpack(p.offset))) end
    elseif object:IsA("Attachment") then
        if p.local_cframe then put("CFrame", CFrame.new(table.unpack(p.local_cframe))) end
        put("Visible", p.visible)
    end
    return object, placeholder and ("placeholder for " .. node.class) or nil
end

local function restoreJson(scene)
    assert(scene.schema == "roblox-rea.scene.v1", "Unsupported scene schema")
    assert(type(scene.nodes) == "table" and #scene.nodes > 0 and #scene.nodes <= MAX_NODES, "Bad node count")
    local objects = {}
    local warnings = 0
    for _, node in ipairs(scene.nodes) do
        local object, warning = reconstructNode(node)
        if object then objects[node.id] = object end
        if warning then warnings = warnings + 1 end
    end
    local destination = importFolder()
    for _, node in ipairs(scene.nodes) do
        local object = objects[node.id]
        if object then
            local parent = node.parent_id and objects[node.parent_id] or destination
            object.Parent = parent or destination
        end
    end
    local rootObject = objects[scene.root_id]
    assert(rootObject, "Cannot reconstruct the selected root class")
    Selection:Set({rootObject})
    return rootObject, warnings
end

local function decoded(response)
    return HttpService:JSONDecode(response.Body)
end

actionButton("1 · Scan selection → save JSON", function()
    doAction("Scanning selected model", function()
        local scene = scanMap(selectedMap())
        local result = decoded(request("POST", "/v1/captures", HttpService:JSONEncode(scene), "application/json"))
        captureField.Text = result.capture_id
        setStatus("Saved " .. tostring(result.nodes) .. " nodes. Capture ID: " .. result.capture_id)
    end)
end)

actionButton("2 · Native backup → RBXM", function()
    doAction("Serializing native RBXM", function()
        local selected = selectedMap()
        local data = SerializationService:SerializeInstancesAsync({selected})
        local bytes = buffer.tostring(data)
        local response = request("POST", "/v1/native", bytes, "application/octet-stream", {
            ["X-REA-Name"] = HttpService:UrlEncode(selected.Name),
        })
        local result = decoded(response)
        nativeField.Text = result.native_id
        setStatus("RBXM backed up: " .. result.native_id .. " (" .. tostring(result.bytes) .. " bytes)")
    end)
end)

actionButton("3 · Restore native RBXM (exact)", function()
    doAction("Loading native RBXM", function()
        local nativeId = nativeField.Text:gsub("%s", "")
        assert(nativeId:match("^[0-9a-f]+$") and #nativeId == 32, "Enter a 32-character native ID")
        local response = request("GET", "/v1/native/" .. nativeId)
        local objects = SerializationService:DeserializeInstancesAsync(buffer.fromstring(response.Body))
        assert(#objects > 0, "The RBXM was empty")
        local destination = importFolder()
        for _, object in ipairs(objects) do
            object.Parent = destination
        end
        Selection:Set(objects)
        setStatus("Restored " .. tostring(#objects) .. " root objects to ServerStorage.REA_Imports")
    end)
end)

actionButton("4 · Reconstruct JSON geometry", function()
    doAction("Reconstructing supported geometry", function()
        local captureId = captureField.Text:gsub("%s", "")
        assert(captureId:match("^[0-9a-f]+$") and #captureId == 32, "Enter a 32-character capture ID")
        local scene = decoded(request("GET", "/v1/captures/" .. captureId))
        local object, warnings = restoreJson(scene)
        setStatus("Rebuilt " .. object.Name .. " in ServerStorage. Approximation warnings: " .. tostring(warnings))
    end)
end)

actionButton("5 · Duplicate locally (Studio clone)", function()
    doAction("Cloning selected model", function()
        local source = selectedMap()
        local clone = source:Clone()
        assert(clone ~= nil, "Clone failed (check Archivable)")
        clone.Name = source.Name .. "_REA_Copy"
        clone.Parent = importFolder()
        Selection:Set({clone})
        setStatus("Cloned " .. source.Name .. " to ServerStorage.REA_Imports")
    end)
end)

textLabel("Scope: current Studio project only. Scripts and Terrain are not reproduced by JSON reconstruction. For highest fidelity, use native RBXM.", 66, Color3.fromRGB(166, 175, 191))
root.CanvasSize = UDim2.new(0, 0, 0, 0)
root.AutomaticCanvasSize = Enum.AutomaticSize.Y

toggle.Click:Connect(function()
    widget.Enabled = not widget.Enabled
end)
