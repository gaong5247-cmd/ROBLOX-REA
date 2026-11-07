-- ROBLOX-REA v0.5 | Studio plugin (not a LocalScript or executor script)
-- Purpose: document, back up and reconstruct maps in experiences you own or may edit.
-- All network calls are local to http://127.0.0.1:8787 and use a private token.
-- REA-RBX never reads other running Roblox clients or private server contents.

local HttpService = game:GetService("HttpService")
local Selection = game:GetService("Selection")
local ServerStorage = game:GetService("ServerStorage")
local SerializationService = game:GetService("SerializationService")
local ChangeHistoryService = game:GetService("ChangeHistoryService")
local RunService = game:GetService("RunService")

local API = "http://127.0.0.1:8787"
local MAX_NODES = 15000
local TERRAIN_TILE = 32 -- cells, 128 studs
local MAX_TERRAIN_TILES = 48
local MAX_CAPTURE_BYTES = 12 * 1024 * 1024
local toolbar = plugin:CreateToolbar("ROBLOX-REA")
local toggle = toolbar:CreateButton("ROBLOX-REA", "Open map scanner and reconstruction tools", "")
local widgetInfo = DockWidgetPluginGuiInfo.new(Enum.InitialDockState.Float, false, false, 450, 570, 350, 420)
local widget = plugin:CreateDockWidgetPluginGui("ROBLOX_REA_v04", widgetInfo)
widget.Title = "ROBLOX-REA · Fidelity Lab"

local root
local displayOrder = 0
local function newGui(className, props, parent)
    local instance = Instance.new(className)
    for key, value in pairs(props or {}) do
        instance[key] = value
    end
    if root and parent == root and instance:IsA("GuiObject") then
        displayOrder = displayOrder + 1
        instance.LayoutOrder = displayOrder
    end
    instance.Parent = parent
    return instance
end

root = newGui("ScrollingFrame", {
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

textLabel("ROBLOX-REA  ·  v0.5", 27, Color3.fromRGB(109, 173, 255)).TextSize = 19
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
textLabel("Script inventory ID (metadata only)", 20)
local scriptField = textInput("Inventory ID appears after script scan", 36)
textLabel("Native model ID (from RBXM backup)", 20)
local nativeField = textInput("Native ID appears after backup", 36)
textLabel("Rescue Package ID (full native + optional Terrain)", 20)
local packageField = textInput("Package ID appears after rescue capture", 36)
textLabel("Terrain area margin (studs, selection bounds)", 20)
local marginField = textInput("16", 34)
marginField.Text = "16"
textLabel("Terrain apply confirmation (type APPLY TERRAIN)", 20)
local confirmTerrain = textInput("Leave empty to keep Terrain unchanged", 34)
textLabel("Repair apply confirmation (type APPLY REPAIR)", 20)
local confirmRepair = textInput("Leave empty for diagnosis only", 34)
local status = textLabel("Ready. Select your own Studio map.", 82, Color3.fromRGB(180, 231, 198))
local planDisplay = textLabel("Doctor review: click 13 to show up to 8 proposed changes. Nothing is applied without typing APPLY REPAIR.", 158, Color3.fromRGB(194, 201, 220))
planDisplay.Font = Enum.Font.Code
planDisplay.TextSize = 11

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
    if ok then return value end -- preserves valid `false` values (e.g. disabled scripts)
    return nil
end

-- Only primitive and explicitly typed Roblox Attribute values are serialized.
local function encodeAttribute(v)
    local t = typeof(v)
    if t == "string" or t == "boolean" or t == "number" then return v end
    local values
    if t == "Vector2" then values = {v.X, v.Y}
    elseif t == "Vector3" then values = {v.X, v.Y, v.Z}
    elseif t == "Color3" then values = {v.R, v.G, v.B}
    elseif t == "CFrame" then values = cframe(v)
    elseif t == "UDim" then values = {v.Scale, v.Offset}
    elseif t == "UDim2" then values = {v.X.Scale, v.X.Offset, v.Y.Scale, v.Y.Offset}
    elseif t == "NumberRange" then values = {v.Min, v.Max}
    elseif t == "Rect" then values = {v.Min.X, v.Min.Y, v.Max.X, v.Max.Y}
    elseif t == "BrickColor" then values = {v.Number}
    else return nil end
    return {t = t, v = values}
end

local function metadata(instance)
    local tags = {}
    for _, tag in ipairs(instance:GetTags()) do
        if #tags >= 32 then break end
        if type(tag) == "string" and #tag > 0 and #tag <= 80 then
            table.insert(tags, tag)
        end
    end
    table.sort(tags)
    local attributes = {}
    local keys = {}
    for key in pairs(instance:GetAttributes()) do table.insert(keys, key) end
    table.sort(keys)
    local original = instance:GetAttributes()
    for _, key in ipairs(keys) do
        if #keys > 1000 then break end
        if type(key) == "string" and #key > 0 and #key <= 100 then
            local ok, value = pcall(encodeAttribute, original[key])
            if ok and value ~= nil and #key <= 100 then
                attributes[key] = value
                if (function()
                    local n = 0
                    for _ in pairs(attributes) do n = n + 1 end
                    return n
                end)() >= 32 then break end
            end
        end
    end
    return tags, attributes
end

local function decodeAttribute(data)
    if type(data) ~= "table" or type(data.t) ~= "string" or type(data.v) ~= "table" then
        return data
    end
    local t, a = data.t, data.v
    if t == "Vector2" and #a == 2 then return Vector2.new(a[1], a[2]) end
    if t == "Vector3" and #a == 3 then return Vector3.new(a[1], a[2], a[3]) end
    if t == "Color3" and #a == 3 then return Color3.new(a[1], a[2], a[3]) end
    if t == "CFrame" and #a == 12 then return CFrame.new(table.unpack(a)) end
    if t == "UDim" and #a == 2 then return UDim.new(a[1], a[2]) end
    if t == "UDim2" and #a == 4 then return UDim2.new(table.unpack(a)) end
    if t == "NumberRange" and #a == 2 then return NumberRange.new(a[1], a[2]) end
    if t == "Rect" and #a == 4 then
        return Rect.new(Vector2.new(a[1], a[2]), Vector2.new(a[3], a[4]))
    end
    if t == "BrickColor" and #a == 1 then return BrickColor.new(a[1]) end
    return nil
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
    elseif instance:IsA("Light") then
        p.brightness = instance.Brightness
        p.color = color3(instance.Color)
        p.enabled = instance.Enabled
        p.shadows = instance.Shadows
        if instance:IsA("PointLight") or instance:IsA("SpotLight") then p.range = instance.Range end
        if instance:IsA("SpotLight") or instance:IsA("SurfaceLight") then
            p.angle = instance.Angle
            p.face = instance.Face.Name
        end
    elseif instance:IsA("Sound") then
        p.sound_id = instance.SoundId
        p.volume = instance.Volume
        p.playback_speed = instance.PlaybackSpeed
        p.looped = instance.Looped
        p.rolloff_max_distance = instance.RollOffMaxDistance
        p.rolloff_min_distance = instance.RollOffMinDistance
    elseif instance:IsA("Script") or instance:IsA("LocalScript") then
        p.enabled = safeProperty(instance, "Enabled")
        if instance:IsA("Script") then
            local runContext = safeProperty(instance, "RunContext")
            p.run_context = runContext and runContext.Name or nil
        end
        -- Script.Source is intentionally NOT read or sent to the bridge.
    elseif instance:IsA("SurfaceAppearance") then
        p.color_map = instance.ColorMap
        p.metalness_map = instance.MetalnessMap
        p.normal_map = instance.NormalMap
        p.roughness_map = instance.RoughnessMap
    end
    return p
end

local REFERENCE_FIELDS = {
    WeldConstraint = {"Part0", "Part1"}, Weld = {"Part0", "Part1"},
    Motor6D = {"Part0", "Part1"}, ManualWeld = {"Part0", "Part1"},
    Snap = {"Part0", "Part1"}, NoCollisionConstraint = {"Part0", "Part1"},
    RigidConstraint = {"Attachment0", "Attachment1"},
    HingeConstraint = {"Attachment0", "Attachment1"},
    BallSocketConstraint = {"Attachment0", "Attachment1"},
    RopeConstraint = {"Attachment0", "Attachment1"},
    RodConstraint = {"Attachment0", "Attachment1"},
    SpringConstraint = {"Attachment0", "Attachment1"},
    PrismaticConstraint = {"Attachment0", "Attachment1"},
    CylindricalConstraint = {"Attachment0", "Attachment1"},
    UniversalConstraint = {"Attachment0", "Attachment1"},
    PlaneConstraint = {"Attachment0", "Attachment1"},
    TorsionSpringConstraint = {"Attachment0", "Attachment1"},
    AlignPosition = {"Attachment0", "Attachment1"},
    AlignOrientation = {"Attachment0", "Attachment1"},
    Beam = {"Attachment0", "Attachment1"}, Trail = {"Attachment0", "Attachment1"},
    VectorForce = {"Attachment0"}, Torque = {"Attachment0"},
    LineForce = {"Attachment0", "Attachment1"},
    AngularVelocity = {"Attachment0"}, LinearVelocity = {"Attachment0"},
    ObjectValue = {"Value"},
}

local function scanMap(source)
    local nodes = {}
    local idByInstance = {}
    local pathToInstance = {}
    local instanceById = {}
    local stack = {{instance = source, parent_id = nil, path = "root"}}
    while #stack > 0 do
        local entry = table.remove(stack)
        assert(#nodes < MAX_NODES, "This capture exceeds the 15,000-node limit")
        local nextId = "n" .. tostring(#nodes + 1)
        idByInstance[entry.instance] = nextId
        instanceById[nextId] = entry.instance
        pathToInstance[entry.path] = entry.instance
        local tags, attrs = metadata(entry.instance)
        local node = {
            id = nextId,
            parent_id = entry.parent_id,
            name = entry.instance.Name ~= "" and entry.instance.Name or "Unnamed",
            class = entry.instance.ClassName,
            path = entry.path,
            properties = getProperties(entry.instance),
            tags = tags,
            attributes = attrs,
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
    -- Two-pass capture is required: references may point to nodes that were
    -- visited later in the depth-first traversal.
    for _, node in ipairs(nodes) do
        local instance = instanceById[node.id]
        local fields = REFERENCE_FIELDS[instance.ClassName]
        if fields then
            local links = {}
            local outside = {}
            for _, field in ipairs(fields) do
                local target = safeProperty(instance, field)
                if typeof(target) == "Instance" then
                    if idByInstance[target] then
                        links[field] = idByInstance[target]
                    else
                        table.insert(outside, field)
                    end
                end
            end
            if next(links) then node.references = links end
            if #outside > 0 then node.external_references = outside end
        end
    end
    return {
        schema = "roblox-rea.scene.v1",
        scene_name = source.Name ~= "" and source.Name or "Unnamed",
        root_id = "n1",
        captured_at = os.time(),
        source = {kind = "studio-selection", place_id = game.PlaceId, root_class = source.ClassName},
        nodes = nodes,
    }, pathToInstance
end

local busy = false
local function doAction(title, callback)
    if busy then
        setStatus("Another REA action is in progress", true)
        return
    end
    busy = true
    setStatus(title .. "...", false)
    local ok, err = pcall(callback)
    if not ok then
        setStatus(err, true)
        warn("[ROBLOX-REA] " .. tostring(err))
    end
    busy = false
end

local function recordChanges(name, callback)
    local recording = ChangeHistoryService:TryBeginRecording("REA_" .. name, "ROBLOX-REA: " .. name)
    assert(recording, "Cannot start Studio undo recording (stop Play mode or finish another action)")
    local outcome = table.pack(pcall(callback))
    ChangeHistoryService:FinishRecording(recording,
        outcome[1] and Enum.FinishRecordingOperation.Commit or Enum.FinishRecordingOperation.Cancel)
    if not outcome[1] then error(outcome[2]) end
    return table.unpack(outcome, 2, outcome.n)
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
    PointLight = true, SpotLight = true, SurfaceLight = true,
    Sound = true, SurfaceAppearance = true,
}
for className in pairs(REFERENCE_FIELDS) do ALLOWED[className] = true end

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
    elseif object:IsA("Light") then
        put("Brightness", p.brightness)
        if p.color then put("Color", Color3.new(table.unpack(p.color))) end
        put("Enabled", p.enabled)
        put("Shadows", p.shadows)
        put("Range", p.range)
        put("Angle", p.angle)
        if p.face and Enum.NormalId[p.face] then put("Face", Enum.NormalId[p.face]) end
    elseif object:IsA("Sound") then
        put("SoundId", p.sound_id)
        put("Volume", p.volume)
        put("PlaybackSpeed", p.playback_speed)
        put("Looped", p.looped)
        put("RollOffMaxDistance", p.rolloff_max_distance)
        put("RollOffMinDistance", p.rolloff_min_distance)
    elseif object:IsA("SurfaceAppearance") then
        put("ColorMap", p.color_map)
        put("MetalnessMap", p.metalness_map)
        put("NormalMap", p.normal_map)
        put("RoughnessMap", p.roughness_map)
    end
    for _, tag in ipairs(node.tags or {}) do
        pcall(function() object:AddTag(tag) end)
    end
    for key, value in pairs(node.attributes or {}) do
        local ok, decoded = pcall(decodeAttribute, value)
        if ok and decoded ~= nil then
            pcall(function() object:SetAttribute(key, decoded) end)
        end
    end
    return object, placeholder and ("placeholder for " .. node.class) or nil
end

local function buildScene(scene, destination, existingByPath)
    assert(scene.schema == "roblox-rea.scene.v1", "Unsupported scene schema")
    assert(type(scene.nodes) == "table" and #scene.nodes > 0 and #scene.nodes <= MAX_NODES, "Bad node count")
    local objects = {}
    local created = {}
    local nodesById = {}
    local warnings = 0
    local built = 0
    for _, node in ipairs(scene.nodes) do
        assert(type(node.id) == "string" and type(node.name) == "string", "Invalid scene node")
        nodesById[node.id] = node
        local preserved = existingByPath and existingByPath[node.path]
        if preserved then
            objects[node.id] = preserved
            if preserved.ClassName ~= node.class then warnings = warnings + 1 end
        else
            local object, warning = reconstructNode(node)
            if object then
                objects[node.id] = object
                created[node.id] = true
                built = built + 1
            end
            if warning or not object then warnings = warnings + 1 end
        end
    end
    local rootObject = objects[scene.root_id]
    assert(rootObject, "Cannot reconstruct root; use a Model/Folder/Part source")
    for _, node in ipairs(scene.nodes) do
        local object = objects[node.id]
        if object and created[node.id] then
            local parent = destination
            local parentId = node.parent_id
            local depth = 0
            while parentId and depth < MAX_NODES do
                if objects[parentId] then
                    parent = objects[parentId]
                    break
                end
                local ancestor = nodesById[parentId]
                parentId = ancestor and ancestor.parent_id or nil
                depth = depth + 1
            end
            object.Parent = parent
        end
    end
    -- Resolve only captured, internal links, and only on newly created objects.
    -- Native objects retain the engine's original references untouched.
    local linksRestored = 0
    for _, node in ipairs(scene.nodes) do
        local object = objects[node.id]
        if object and created[node.id] then
            for field, targetId in pairs(node.references or {}) do
                local target = objects[targetId]
                local allowed = REFERENCE_FIELDS[node.class]
                if target and allowed and table.find(allowed, field) then
                    local ok = pcall(function() object[field] = target end)
                    if ok then linksRestored = linksRestored + 1 else warnings = warnings + 1 end
                else
                    warnings = warnings + 1
                end
            end
        end
    end
    return rootObject, warnings, built, linksRestored
end

local function restoreJson(scene)
    local object, warnings, built, links = buildScene(scene, importFolder(), nil)
    Selection:Set({object})
    return object, warnings, built, links
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

actionButton("3 · Restore native RBXM (Studio)", function()
    doAction("Loading native RBXM", function()
        local nativeId = nativeField.Text:gsub("%s", "")
        assert(nativeId:match("^[0-9a-f]+$") and #nativeId == 32, "Enter a 32-character native ID")
        local response = request("GET", "/v1/native/" .. nativeId)
        local objects = SerializationService:DeserializeInstancesAsync(buffer.fromstring(response.Body))
        assert(#objects > 0, "The RBXM was empty")
        recordChanges("Restore native model", function()
            local destination = importFolder()
            for _, object in ipairs(objects) do object.Parent = destination end
            Selection:Set(objects)
        end)
        setStatus("Restored " .. tostring(#objects) .. " root objects to ServerStorage.REA_Imports")
    end)
end)

actionButton("4 · Reconstruct JSON geometry", function()
    doAction("Reconstructing supported geometry", function()
        local captureId = captureField.Text:gsub("%s", "")
        assert(captureId:match("^[0-9a-f]+$") and #captureId == 32, "Enter a 32-character capture ID")
        local scene = decoded(request("GET", "/v1/captures/" .. captureId))
        local object, warnings = recordChanges("Reconstruct JSON", function()
            return restoreJson(scene)
        end)
        setStatus("Rebuilt " .. object.Name .. " in ServerStorage. Approximation warnings: " .. tostring(warnings))
    end)
end)

actionButton("5 · Duplicate locally (Studio clone)", function()
    doAction("Cloning selected model", function()
        local source = selectedMap()
        local clone = source:Clone()
        assert(clone ~= nil, "Clone failed (check Archivable)")
        clone.Name = source.Name .. "_REA_Copy"
        recordChanges("Duplicate model", function()
            clone.Parent = importFolder()
            Selection:Set({clone})
        end)
        setStatus("Cloned " .. source.Name .. " to ServerStorage.REA_Imports")
    end)
end)

actionButton("6 · Compare selection ↔ saved capture", function()
    doAction("Comparing current Studio map to capture", function()
        local captureId = captureField.Text:gsub("%s", "")
        assert(captureId:match("^[0-9a-f]+$") and #captureId == 32, "Enter a 32-character capture ID")
        local current = scanMap(selectedMap())
        local response = decoded(request("POST", "/v1/compare/" .. captureId,
            HttpService:JSONEncode(current), "application/json"))
        local counts = response.counts
        local message = "Added: " .. tostring(counts.added) .. " | Removed: "
            .. tostring(counts.removed) .. " | Changed: " .. tostring(counts.modified)
        if #response.modified_details > 0 then
            local entry = response.modified_details[1]
            message = message .. "\nFirst changed: " .. entry.path
        elseif #response.added > 0 then
            message = message .. "\nFirst added: " .. response.added[1]
        elseif #response.removed > 0 then
            message = message .. "\nFirst removed: " .. response.removed[1]
        end
        setStatus(message)
    end)
end)

-- Native terrain is captured only within the bounds of the selected Model/Folder/Part,
-- expanded by a user margin. Tiles include empty cells to avoid silent data loss.
local function selectionBounds(source)
    local low = Vector3.new(math.huge, math.huge, math.huge)
    local high = Vector3.new(-math.huge, -math.huge, -math.huge)
    local count = 0
    local function includePart(part)
        if part:IsA("BasePart") and not part:IsA("Terrain") then
            local cf, h = part.CFrame, part.Size * 0.5
            for x = -1, 1, 2 do
                for y = -1, 1, 2 do
                    for z = -1, 1, 2 do
                        local point = cf:PointToWorldSpace(Vector3.new(x * h.X, y * h.Y, z * h.Z))
                        low = Vector3.new(math.min(low.X, point.X), math.min(low.Y, point.Y), math.min(low.Z, point.Z))
                        high = Vector3.new(math.max(high.X, point.X), math.max(high.Y, point.Y), math.max(high.Z, point.Z))
                    end
                end
            end
            count = count + 1
        end
    end
    includePart(source)
    for _, part in ipairs(source:GetDescendants()) do includePart(part) end
    assert(count > 0, "Selection must contain at least one BasePart to calculate Terrain bounds")
    return low, high
end

local function terrainSettings()
    local terrain = workspace.Terrain
    local properties = {}
    -- Some Terrain editor properties are NotScriptable in some Studio builds;
    -- missing values remain absent instead of breaking the native backup.
    local fields = {
        decoration = "Decoration", grass_length = "GrassLength",
        water_reflectance = "WaterReflectance", water_transparency = "WaterTransparency",
        water_wave_size = "WaterWaveSize", water_wave_speed = "WaterWaveSpeed",
    }
    for key, field in pairs(fields) do
        local value = safeProperty(terrain, field)
        if value ~= nil then properties[key] = value end
    end
    local water = safeProperty(terrain, "WaterColor")
    if typeof(water) == "Color3" then properties.water_color = color3(water) end
    local materialColors = {}
    for _, material in ipairs(Enum.Material:GetEnumItems()) do
        local ok, color = pcall(function() return terrain:GetMaterialColor(material) end)
        if ok and typeof(color) == "Color3" then
            materialColors[material.Name] = color3(color)
        end
    end
    properties.material_colors = materialColors
    return properties
end

local function terrainRegionsForSelection(source)
    local minPos, maxPos = selectionBounds(source)
    local margin = tonumber(marginField.Text)
    assert(margin and margin >= 0 and margin <= 256, "Terrain margin must be 0 to 256 studs")
    local mins = {math.floor((minPos.X - margin) / 4),
                  math.floor((minPos.Y - margin) / 4),
                  math.floor((minPos.Z - margin) / 4)}
    local maxs = {math.ceil((maxPos.X + margin) / 4),
                  math.ceil((maxPos.Y + margin) / 4),
                  math.ceil((maxPos.Z + margin) / 4)}
    local counts = {}
    local tiles = 1
    for i = 1, 3 do
        mins[i] = math.max(-32000, math.min(31999, mins[i]))
        maxs[i] = math.max(mins[i] + 1, math.min(32000, maxs[i]))
        counts[i] = math.ceil((maxs[i] - mins[i]) / TERRAIN_TILE)
        tiles = tiles * counts[i]
    end
    assert(tiles <= MAX_TERRAIN_TILES,
        "Terrain selection needs " .. tostring(tiles) .. " tiles (>48). Choose a smaller Model or margin")
    local regions = {}
    for x = mins[1], maxs[1] - 1, TERRAIN_TILE do
        for y = mins[2], maxs[2] - 1, TERRAIN_TILE do
            for z = mins[3], maxs[3] - 1, TERRAIN_TILE do
                local origin = {x, y, z}
                local size = {math.min(TERRAIN_TILE, maxs[1] - x),
                              math.min(TERRAIN_TILE, maxs[2] - y),
                              math.min(TERRAIN_TILE, maxs[3] - z)}
                local region = Region3int16.new(
                    Vector3int16.new(x, y, z),
                    Vector3int16.new(x + size[1], y + size[2], z + size[3]))
                table.insert(regions, {region = region, origin_cells = origin, size_cells = size})
            end
        end
    end
    return regions
end

local function sendNative(data, name, kind)
    local response = request("POST", "/v1/native", buffer.tostring(data),
        "application/octet-stream", {
            ["X-REA-Name"] = HttpService:UrlEncode(name),
            ["X-REA-Kind"] = kind,
        })
    return decoded(response)
end

local function assertHexId(id, label)
    local clean = id:gsub("%s", "")
    assert(#clean == 32 and clean:match("^[0-9a-f]+$"), label .. " must contain 32 hex digits")
    return clean
end

actionButton("7 · Rescue: native model + Terrain", function()
    doAction("Capturing full-rescue package", function()
        local source = selectedMap()
        local regions = terrainRegionsForSelection(source)
        local scene = scanMap(source)
        local sceneResult = decoded(request("POST", "/v1/captures", HttpService:JSONEncode(scene), "application/json"))
        captureField.Text = sceneResult.capture_id
        local nativeResult = sendNative(SerializationService:SerializeInstancesAsync({source}), source.Name, "model")
        nativeField.Text = nativeResult.native_id
        local chunks = {}
        for i, tile in ipairs(regions) do
            setStatus("Backing up Terrain " .. tostring(i) .. "/" .. tostring(#regions))
            local terrainRegion = workspace.Terrain:CopyRegion(tile.region)
            local ok, tileData = pcall(function()
                local encoded = SerializationService:SerializeInstancesAsync({terrainRegion})
                -- Fail rather than pretending a backup is high-fidelity when the
                -- current Studio engine cannot deserialize its TerrainRegion.
                local probe = SerializationService:DeserializeInstancesAsync(encoded)
                local good = #probe == 1 and probe[1]:IsA("TerrainRegion")
                if good then
                    local dims = probe[1].SizeInCells
                    good = dims.X == tile.size_cells[1] and dims.Y == tile.size_cells[2]
                        and dims.Z == tile.size_cells[3]
                end
                for _, object in ipairs(probe) do object:Destroy() end
                assert(good, "TerrainRegion roundtrip mismatch")
                return encoded
            end)
            terrainRegion:Destroy()
            assert(ok, "Studio could not serialize TerrainRegion tile " .. tostring(i) .. ": " .. tostring(tileData))
            local tileInfo = sendNative(tileData, source.Name .. " terrain tile " .. tostring(i), "terrain")
            table.insert(chunks, {
                native_id = tileInfo.native_id,
                origin_cells = tile.origin_cells,
                size_cells = tile.size_cells,
            })
        end
        local manifest = {
            name = source.Name,
            capture_id = sceneResult.capture_id,
            native_id = nativeResult.native_id,
            terrain_chunks = chunks,
            terrain_settings = terrainSettings(),
        }
        local package = decoded(request("POST", "/v1/packages",
            HttpService:JSONEncode(manifest), "application/json"))
        packageField.Text = package.package_id
        setStatus("Rescue saved! " .. tostring(#chunks) .. " Terrain tiles. Package: " .. package.package_id)
    end)
end)

local function readPackage()
    local id = assertHexId(packageField.Text, "Rescue Package ID")
    local result = decoded(request("GET", "/v1/packages/" .. id .. "/verify"))
    assert(result.ok == true, "Rescue verification failed. See local CLI: rea-rbx verify " .. id)
    local package = decoded(request("GET", "/v1/packages/" .. id))
    assert(package.schema == "roblox-rea.rescue.v1", "Unknown rescue format")
    assert(package.package_id == id, "Package ID mismatch")
    return package
end

local function deserializeNative(nativeId)
    local bytes = request("GET", "/v1/native/" .. assertHexId(nativeId, "Native ID")).Body
    return SerializationService:DeserializeInstancesAsync(buffer.fromstring(bytes))
end

actionButton("8 · Stage rescue into ServerStorage (safe)", function()
    doAction("Staging native rescue", function()
        local package = readPackage()
        local models = deserializeNative(package.native_id)
        assert(#models > 0, "Rescue model is empty")
        local staged = {}
        local terrainTiles = {}
        for i, chunk in ipairs(package.terrain_chunks) do
            setStatus("Loading rescue Terrain " .. tostring(i) .. "/" .. tostring(#package.terrain_chunks))
            local parsed = deserializeNative(chunk.native_id)
            assert(#parsed == 1 and parsed[1]:IsA("TerrainRegion"),
                "Rescue contains unexpected Terrain content at tile " .. tostring(i))
            table.insert(terrainTiles, parsed[1])
        end
        recordChanges("Stage full rescue", function()
            local destination = importFolder()
            local stage = Instance.new("Folder")
            stage.Name = "REA_Rescue_" .. package.package_id
            stage.Parent = destination
            local modelFolder = Instance.new("Folder")
            modelFolder.Name = "Models"
            modelFolder.Parent = stage
            local terrainFolder = Instance.new("Folder")
            terrainFolder.Name = "Terrain_Tiles_Staged_NotApplied"
            terrainFolder.Parent = stage
            for _, object in ipairs(models) do object.Parent = modelFolder end
            for i, region in ipairs(terrainTiles) do
                region.Name = "Tile_" .. tostring(i)
                region.Parent = terrainFolder
            end
            Selection:Set({stage})
            table.insert(staged, stage)
        end)
        setStatus("Staged native model + " .. tostring(#terrainTiles)
            .. " Terrain tiles in ServerStorage. World Terrain has NOT been changed.")
    end)
end)

actionButton("9 · APPLY Terrain to Workspace (overwrite!)", function()
    doAction("Applying Terrain with undo recording", function()
        assert(confirmTerrain.Text == "APPLY TERRAIN", "Type APPLY TERRAIN to allow voxel overwrite")
        local package = readPackage()
        assert(#package.terrain_chunks > 0, "Package contains no Terrain tiles")
        -- Load everything and check metadata BEFORE touching the Workspace.
        local tileData = {}
        for i, chunk in ipairs(package.terrain_chunks) do
            local parsed = deserializeNative(chunk.native_id)
            assert(#parsed == 1 and parsed[1]:IsA("TerrainRegion"),
                "Tile " .. tostring(i) .. " is not a TerrainRegion")
            local region = parsed[1]
            local size = region.SizeInCells
            assert(size.X == chunk.size_cells[1] and size.Y == chunk.size_cells[2]
                   and size.Z == chunk.size_cells[3], "Terrain tile size mismatch " .. tostring(i))
            table.insert(tileData, {region = region, position = Vector3int16.new(
                chunk.origin_cells[1], chunk.origin_cells[2], chunk.origin_cells[3])})
        end
        local applied = recordChanges("Overwrite Terrain from rescue", function()
            for i, tile in ipairs(tileData) do
                setStatus("Pasting Terrain " .. tostring(i) .. "/" .. tostring(#tileData))
                workspace.Terrain:PasteRegion(tile.region, tile.position, true)
            end
            local properties = package.terrain_settings or {}
            local terrain = workspace.Terrain
            local mapping = {
                decoration = "Decoration", grass_length = "GrassLength",
                water_reflectance = "WaterReflectance", water_transparency = "WaterTransparency",
                water_wave_size = "WaterWaveSize", water_wave_speed = "WaterWaveSpeed",
            }
            for field, property in pairs(mapping) do
                if properties[field] ~= nil then pcall(function() terrain[property] = properties[field] end) end
            end
            if properties.water_color then
                pcall(function() terrain.WaterColor = Color3.new(table.unpack(properties.water_color)) end)
            end
            for material, color in pairs(properties.material_colors or {}) do
                local item = Enum.Material[material]
                if item then pcall(function() terrain:SetMaterialColor(item, Color3.new(table.unpack(color))) end) end
            end
            return #tileData
        end)
        for _, tile in ipairs(tileData) do tile.region:Destroy() end
        confirmTerrain.Text = ""
        setStatus("Terrain restored: " .. tostring(applied)
            .. " tiles. Existing voxels inside the tile bounds were overwritten; Studio Undo is available.")
    end)
end)

-- v0.4: High-fidelity native-first hybrid restoration. Never places imported
-- objects into the live Workspace or overwrites Terrain automatically.
actionButton("10 · HYBRID: native + JSON fallback (stage)", function()
    doAction("Staging hybrid reconstruction", function()
        local captureId, nativeId
        local packageText = packageField.Text:gsub("%s", "")
        if #packageText > 0 then
            local packageId = assertHexId(packageText, "Package ID")
            local package = decoded(request("GET", "/v1/packages/" .. packageId))
            assert(package.package_id == packageId and package.schema == "roblox-rea.rescue.v1", "Invalid package")
            captureId, nativeId = package.capture_id, package.native_id
        else
            captureId = assertHexId(captureField.Text, "Capture ID")
            nativeId = assertHexId(nativeField.Text, "Native ID")
        end
        local scene = decoded(request("GET", "/v1/captures/" .. captureId))
        assert(scene.schema == "roblox-rea.scene.v1", "Unsupported scene schema")
        local nativeOk, nativeModels = pcall(deserializeNative, nativeId)
        local nativeRoot = nil
        if nativeOk and #nativeModels == 1 and nativeModels[1].ClassName == scene.nodes[1].class then
            nativeRoot = nativeModels[1]
        else
            if nativeOk then
                for _, model in ipairs(nativeModels) do model:Destroy() end
            end
        end
        local rootObject, warnings, built, links = recordChanges("Hybrid rescue stage", function()
            local stage = Instance.new("Folder")
            stage.Name = "REA_Hybrid_" .. captureId
            stage.Parent = importFolder()
            local indexed = nil
            if nativeRoot then
                nativeRoot.Parent = stage
                local _, paths = scanMap(nativeRoot)
                indexed = paths
            end
            local root, warnCount, createdCount, linkCount = buildScene(scene, stage, indexed)
            Selection:Set({root})
            return root, warnCount, createdCount, linkCount
        end)
        captureField.Text = captureId
        nativeField.Text = nativeId
        setStatus("Hybrid staged in ServerStorage: " .. rootObject.Name
            .. " | native: " .. tostring(nativeRoot ~= nil)
            .. " | JSON nodes recovered: " .. tostring(built)
            .. " | links: " .. tostring(links) .. " | warnings: " .. tostring(warnings))
    end)
end)

-- Studio-only visual diagnostics. Preview objects are non-archivable and may
-- be deleted with one button; no source object is recolored or moved.
local previewFolder = nil
local MAX_DIFF_MARKERS = 60
local function clearDiffMarkers()
    if previewFolder then
        previewFolder:Destroy()
        previewFolder = nil
    end
end

local function diffHighlight(parent, adornee, shade)
    local highlight = Instance.new("Highlight")
    highlight.Name = "REA_DiffMarker"
    highlight.Archivable = false
    highlight.FillColor = shade
    highlight.OutlineColor = shade
    highlight.FillTransparency = 0.8
    highlight.OutlineTransparency = 0
    highlight.DepthMode = Enum.HighlightDepthMode.AlwaysOnTop
    highlight.Adornee = adornee
    highlight.Parent = parent
end

actionButton("11 · Preview 3D differences (green/yellow/red)", function()
    doAction("Building 3D difference preview", function()
        local captureId = assertHexId(captureField.Text, "Capture ID")
        local source = selectedMap()
        local current, pathIndex = scanMap(source)
        local baseline = decoded(request("GET", "/v1/captures/" .. captureId))
        local report = decoded(request("POST", "/v1/compare/" .. captureId,
            HttpService:JSONEncode(current), "application/json"))
        clearDiffMarkers()
        previewFolder = Instance.new("Folder")
        previewFolder.Name = "__REA_DiffPreview_" .. captureId:sub(1, 8)
        previewFolder.Archivable = false
        previewFolder.Parent = workspace
        local marked = 0
        local colors = {
            added = Color3.fromRGB(40, 250, 145),
            modified = Color3.fromRGB(245, 207, 54),
            removed = Color3.fromRGB(245, 67, 73),
        }
        local function mark(path, shade)
            if marked >= MAX_DIFF_MARKERS then return end
            local target = pathIndex[path]
            while target and not (target:IsA("BasePart") or target:IsA("Model")) do
                if target == source then break end
                target = target.Parent
            end
            if target and (target:IsA("BasePart") or target:IsA("Model")) then
                diffHighlight(previewFolder, target, shade)
                marked = marked + 1
            end
        end
        for _, path in ipairs(report.added or {}) do mark(path, colors.added) end
        for _, path in ipairs(report.modified or {}) do mark(path, colors.modified) end
        local nodes = {}
        for _, node in ipairs(baseline.nodes or {}) do nodes[node.path] = node end
        for _, path in ipairs(report.removed or {}) do
            if marked >= MAX_DIFF_MARKERS then break end
            local props = nodes[path] and nodes[path].properties or {}
            if type(props.size) == "table" and type(props.cframe) == "table" then
                local ghost = Instance.new("Part")
                ghost.Name = "REA_Missing_Ghost"
                ghost.Archivable = false
                ghost.Anchored = true
                ghost.CanCollide = false
                ghost.CanTouch = false
                ghost.CanQuery = false
                ghost.CastShadow = false
                ghost.Transparency = 0.99 -- 1.0 can suppress highlights in Studio
                ghost.Locked = true
                ghost.Size = Vector3.new(table.unpack(props.size))
                ghost.CFrame = CFrame.new(table.unpack(props.cframe))
                ghost.Parent = previewFolder
                diffHighlight(previewFolder, ghost, colors.removed)
                marked = marked + 1
            end
        end
        local counts = report.counts
        setStatus("3D diff: +" .. tostring(counts.added) .. " / -" .. tostring(counts.removed)
            .. " / ~" .. tostring(counts.modified)
            .. ". Green added, yellow changed, red missing. " .. tostring(marked)
            .. " markers (max " .. tostring(MAX_DIFF_MARKERS) .. "). Use Clear to remove.")
    end)
end)

actionButton("12 · Clear 3D diff overlay", function()
    doAction("Clearing 3D diff markers", function()
        clearDiffMarkers()
        setStatus("3D diff overlay cleared; source parts unchanged")
    end)
end)

local currentRepair = nil
local function showRepairPlan(plan)
    local lines = {"REPAIR PLAN " .. plan.plan_id:sub(1, 12) .. " (preview only)"}
    local shown = math.min(#plan.operations, 8)
    for i = 1, shown do
        local operation = plan.operations[i]
        local detail = operation.op == "set_reference"
            and ("LINK " .. operation.property .. " -> " .. operation.target_path)
            or ("SET " .. operation.property .. " = " .. HttpService:JSONEncode(operation.value))
        table.insert(lines, tostring(i) .. ". " .. operation.path:sub(1, 80))
        table.insert(lines, "   " .. detail:sub(1, 90))
    end
    if #plan.operations > shown then
        table.insert(lines, "+ " .. tostring(#plan.operations - shown) .. " more actions. Export scans for CLI review.")
    end
    if #plan.operations == 0 then table.insert(lines, "No safe edits proposed.") end
    if plan.counts.blocked > 0 then
        table.insert(lines, tostring(plan.counts.blocked) .. " changes require manual review.")
    end
    planDisplay.Text = table.concat(lines, "\n")
    planDisplay.Size = UDim2.new(1, 0, 0, math.max(138, math.min(390, #lines * 16 + 8)))
end
local function calculateRepair(captureId, map)
    local scan = scanMap(map)
    return decoded(request("POST", "/v1/repair/" .. captureId,
        HttpService:JSONEncode(scan), "application/json"))
end

-- Only typed, allowlisted properties can be written. Any failure cancels the
-- complete ChangeHistoryService transaction instead of reporting success.
local PART_KEY_MAP = {
    size = "Size", cframe = "CFrame", color = "Color", material = "Material",
    transparency = "Transparency", reflectance = "Reflectance",
    anchored = "Anchored", can_collide = "CanCollide", can_touch = "CanTouch",
    can_query = "CanQuery", cast_shadow = "CastShadow", shape = "Shape",
}
local OTHER_KEY_MAP = {
    texture = "Texture", face = "Face", studs_per_tile_u = "StudsPerTileU",
    studs_per_tile_v = "StudsPerTileV", local_cframe = "CFrame", visible = "Visible",
    mesh_id = "MeshId", texture_id = "TextureId", mesh_type = "MeshType",
    scale = "Scale", offset = "Offset", brightness = "Brightness",
    enabled = "Enabled", shadows = "Shadows", range = "Range", angle = "Angle",
    sound_id = "SoundId", volume = "Volume", playback_speed = "PlaybackSpeed",
    looped = "Looped", rolloff_max_distance = "RollOffMaxDistance",
    rolloff_min_distance = "RollOffMinDistance", color_map = "ColorMap",
    metalness_map = "MetalnessMap", normal_map = "NormalMap",
    roughness_map = "RoughnessMap", transparency = "Transparency", color = "Color3",
}
local function applyPlannedProperty(object, key, value)
    local prop = object:IsA("BasePart") and PART_KEY_MAP[key] or OTHER_KEY_MAP[key]
    if object:IsA("Light") and key == "color" then prop = "Color" end
    assert(prop, "Repair property is not allowlisted: " .. tostring(key))
    -- Deny cross-class writes even if both classes have a property with the
    -- same name (e.g. a Sound cannot receive attachment properties).
    if object:IsA("BasePart") then
        assert(key ~= "shape" or object:IsA("Part"), "Shape only applies to Part")
    elseif object:IsA("Decal") or object:IsA("Texture") then
        assert(table.find({"texture", "transparency", "face", "color", "studs_per_tile_u", "studs_per_tile_v"}, key))
        assert(key ~= "studs_per_tile_u" and key ~= "studs_per_tile_v" or object:IsA("Texture"))
    elseif object:IsA("Attachment") then
        assert(table.find({"local_cframe", "visible"}, key))
    elseif object:IsA("SpecialMesh") then
        assert(table.find({"mesh_id", "texture_id", "mesh_type", "scale", "offset"}, key))
    elseif object:IsA("Light") then
        assert(table.find({"brightness", "color", "enabled", "shadows", "range", "angle", "face"}, key))
    elseif object:IsA("Sound") then
        assert(table.find({"sound_id", "volume", "playback_speed", "looped", "rolloff_max_distance", "rolloff_min_distance"}, key))
    elseif object:IsA("SurfaceAppearance") then
        assert(table.find({"color_map", "metalness_map", "normal_map", "roughness_map"}, key))
    else
        error("Repair is not allowed for class " .. object.ClassName)
    end
    if key == "cframe" or key == "local_cframe" then
        value = CFrame.new(table.unpack(value))
    elseif key == "size" or key == "scale" or key == "offset" then
        value = Vector3.new(table.unpack(value))
    elseif key == "color" then
        value = Color3.new(table.unpack(value))
    elseif key == "material" then
        value = assert(Enum.Material[value], "Unknown material " .. tostring(value))
    elseif key == "shape" then
        value = assert(Enum.PartType[value], "Unknown part shape")
    elseif key == "face" then
        value = assert(Enum.NormalId[value], "Unknown face")
    elseif key == "mesh_type" then
        value = assert(Enum.MeshType[value], "Unknown mesh type")
    end
    object[prop] = value
end

local function applyPlannedLink(object, field, target)
    local fields = REFERENCE_FIELDS[object.ClassName]
    assert(fields and table.find(fields, field), "Reference type is not allowlisted")
    assert(typeof(target) == "Instance", "Reference target is missing")
    if field == "Part0" or field == "Part1" then
        assert(target:IsA("BasePart"), "Reference target must be a BasePart")
    elseif field == "Attachment0" or field == "Attachment1" then
        assert(target:IsA("Attachment"), "Reference target must be Attachment")
    end
    object[field] = target
end

actionButton("13 · Doctor: preview repair plan", function()
    doAction("Generating read-only repair plan", function()
        local captureId = assertHexId(captureField.Text, "Capture ID")
        local source = selectedMap()
        local plan = calculateRepair(captureId, source)
        assert(plan.schema == "roblox-rea.repair-plan.v1" and #plan.plan_id == 64, "Invalid doctor plan")
        currentRepair = {id = plan.plan_id, capture_id = captureId, selection = source}
        showRepairPlan(plan)
        setStatus("Doctor preview: " .. tostring(plan.counts.planned) .. " safe actions, "
            .. tostring(plan.counts.blocked) .. " manual reviews, "
            .. tostring(plan.counts.missing) .. " missing nodes (use Hybrid), "
            .. tostring(plan.counts.extra_preserved) .. " extra objects preserved. "
            .. "Review the plan above before typing APPLY REPAIR.")
    end)
end)

actionButton("14 · APPLY approved property/link repair", function()
    doAction("Applying approved repair plan", function()
        assert(confirmRepair.Text == "APPLY REPAIR", "Type APPLY REPAIR to approve a bounded edit")
        local source = selectedMap()
        local captureId = assertHexId(captureField.Text, "Capture ID")
        assert(currentRepair and currentRepair.selection == source and currentRepair.capture_id == captureId,
            "Preview this exact selection and capture first")
        -- Recompute on a fresh scan; stale or changed selections cannot use a
        -- previously approved plan from another source state.
        local plan = calculateRepair(captureId, source)
        assert(plan.plan_id == currentRepair.id, "Map changed after preview: regenerate repair plan")
        assert(#plan.operations > 0 and #plan.operations <= 100, "No safe repairs in this plan")
        local _, byPath = scanMap(source)
        local completed = recordChanges("Approved map repair", function()
            for _, operation in ipairs(plan.operations) do
                local target = byPath[operation.path]
                assert(target and target.ClassName == operation.class, "Repair target changed")
                if operation.op == "set_property" then
                    applyPlannedProperty(target, operation.property, operation.value)
                elseif operation.op == "set_reference" then
                    local referenced = byPath[operation.target_path]
                    applyPlannedLink(target, operation.property, referenced)
                else
                    error("Unexpected repair operation")
                end
            end
            return #plan.operations
        end)
        currentRepair = nil
        confirmRepair.Text = ""
        planDisplay.Text = "Repair applied. Preview again to inspect remaining differences."
        local remaining = calculateRepair(captureId, source)
        setStatus("Repaired " .. tostring(completed) .. " properties/links with Studio Undo. "
            .. tostring(remaining.counts.planned) .. " safe actions remain; "
            .. tostring(remaining.counts.blocked) .. " require manual review.")
    end)
end)


-- v0.5: Comparing a staged native/hybrid model is permitted.  Earlier actions
-- remain restricted to a source inside Workspace.  No other service is accepted.
local function selectedForFidelity()
    local selected = Selection:Get()
    assert(#selected == 1, "Select one source model or staged reconstruction")
    local item = selected[1]
    local staged = ServerStorage:FindFirstChild("REA_Imports")
    assert(item:IsA("Model") or item:IsA("Folder") or item:IsA("BasePart"),
        "Select a Model, Folder or BasePart")
    assert(item:IsDescendantOf(workspace) or (staged and item:IsDescendantOf(staged)),
        "Fidelity is limited to Workspace objects and REA_Imports staging")
    assert(not item:IsA("Terrain"), "Terrain voxels require separate region verification")
    return item
end

actionButton("15 · VERIFY map fidelity (read-only)", function()
    doAction("Measuring captured property and connection accuracy", function()
        local captureId = assertHexId(captureField.Text, "Reference capture ID")
        local restored = selectedForFidelity()
        local current = scanMap(restored)
        local result = decoded(request("POST", "/v1/fidelity/" .. captureId,
            HttpService:JSONEncode(current), "application/json"))
        assert(result.schema == "roblox-rea.fidelity-report.v1", "Invalid fidelity report")
        local c = result.counts
        local m = result.measurements
        local message = "Observed: " .. result.observed_status
            .. " | objects " .. tostring(m.node_coverage_percent) .. "%"
            .. " | properties " .. tostring(m.observed_property_match_percent) .. "%"
            .. " | links " .. tostring(m.observed_reference_match_percent) .. "%"
            .. "\nMissing: " .. tostring(c.missing) .. " | extra: " .. tostring(c.unexpected)
            .. " | changed: " .. tostring(c.changed)
            .. "\nPosition max: " .. tostring(m.maximum_position_error_studs) .. " studs"
            .. " | rotation max: " .. tostring(m.maximum_rotation_error_degrees) .. " deg"
            .. "\nMesh shape, Terrain voxels and script source NOT VERIFIED."
        if #result.changed_details > 0 then
            message = message .. "\nFirst mismatch: " .. result.changed_details[1].path
        end
        planDisplay.Text = message
        planDisplay.Size = UDim2.new(1, 0, 0, 166)
        setStatus("Fidelity report ready. Read the numeric measurements above; percentages are metadata-only.")
    end)
end)

-- Inventory is deliberately names/classes/placements/flags only.  v1.0 can
-- add separate, opt-in Studio-only script backup, but source never leaves
-- the editor through this v0.5 endpoint.
local SCRIPT_SERVICES = {
    "Workspace", "ServerScriptService", "ServerStorage", "ReplicatedStorage",
    "ReplicatedFirst", "StarterPlayer", "StarterGui", "StarterPack",
}
local MAX_SCRIPTS = 8000
local MAX_SCRIPT_BYTES = 1024 * 1024
local function scriptInventory()
    assert(not RunService:IsRunning(), "Stop Play/Run to inventory the saved edit-time project")
    local items = {}
    for _, serviceName in ipairs(SCRIPT_SERVICES) do
        local service = game:GetService(serviceName)
        local stack = {{instance = service, path = serviceName}}
        while #stack > 0 do
            local entry = table.remove(stack)
            local object = entry.instance
            if object:IsA("Script") or object:IsA("LocalScript") or object:IsA("ModuleScript") then
                assert(#items < MAX_SCRIPTS, "Too many scripts: inventory was NOT saved")
                local item = {
                    path = entry.path,
                    name = object.Name,
                    class = object.ClassName,
                    service = serviceName,
                    archivable = object.Archivable,
                }
                if object:IsA("Script") or object:IsA("LocalScript") then
                    local enabled = safeProperty(object, "Enabled")
                    if type(enabled) == "boolean" then item.enabled = enabled end
                end
                if object:IsA("Script") then
                    local ctx = safeProperty(object, "RunContext")
                    if ctx and (ctx.Name == "Legacy" or ctx.Name == "Server" or ctx.Name == "Client") then
                        item.run_context = ctx.Name
                    end
                end
                table.insert(items, item)
            end
            local children = object:GetChildren()
            local sibling = {}
            for _, child in ipairs(children) do
                local label = child.ClassName .. ":" .. child.Name
                sibling[label] = (sibling[label] or 0) + 1
                local path = entry.path .. "/" .. label .. "[" .. sibling[label] .. "]"
                assert(#path <= 1024, "Script inventory hierarchy path too long")
                table.insert(stack, {instance = child, path = path})
            end
        end
    end
    return {
        schema = "roblox-rea.script-inventory.v1",
        scope = "authorized-studio-project",
        mode = "metadata-only",
        includes_source = false,
        captured_at = os.time(),
        place_id = game.PlaceId,
        items = items,
    }
end

actionButton("16 · Inventory server/client scripts (NO source)", function()
    doAction("Indexing script placements in this editable Studio place", function()
        local manifest = scriptInventory()
        local body = HttpService:JSONEncode(manifest)
        assert(#body <= MAX_SCRIPT_BYTES, "Script inventory too large; NOT sent")
        local result = decoded(request("POST", "/v1/scripts", body, "application/json"))
        scriptField.Text = result.inventory_id
        local kinds = result.by_class
        setStatus("Saved metadata-only inventory " .. result.inventory_id
            .. "\nScript " .. tostring(kinds.Script or 0)
            .. ", LocalScript " .. tostring(kinds.LocalScript or 0)
            .. ", ModuleScript " .. tostring(kinds.ModuleScript or 0)
            .. ". No code was read or transmitted.")
    end)
end)

plugin.Unloading:Connect(function()
    clearDiffMarkers()
end)

textLabel("Studio projects you own or may edit only. Fidelity scores cover OBSERVED metadata, never mesh triangles, Terrain voxels or Luau source. Script inventory records names/locations only.", 80, Color3.fromRGB(166, 175, 191))
root.CanvasSize = UDim2.new(0, 0, 0, 0)
root.AutomaticCanvasSize = Enum.AutomaticSize.Y

toggle.Click:Connect(function()
    widget.Enabled = not widget.Enabled
end)
