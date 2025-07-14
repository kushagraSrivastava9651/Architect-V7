import ezdxf
from ezdxf.math import Vec2, Vec3, Matrix44
from shapely.geometry import Polygon, Point, LineString
import math
import re
import ezdxf
import math
from ezdxf.math import Matrix44, Vec3
from shapely.geometry import Polygon, Point
from shapely.affinity import affine_transform


def get_entity_points(entity, mat):
    """Extract points from various DXF entity types"""
    try:
        dtype = entity.dxftype()
        points = []
        
        if dtype == "LWPOLYLINE":
            points = [Vec2(x, y) for x, y, *_ in entity.get_points()]
        elif dtype == "POLYLINE":
            points = [Vec2(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        elif dtype == "LINE":
            start = entity.dxf.start
            end = entity.dxf.end
            points = [Vec2(start.x, start.y), Vec2(end.x, end.y)]
        elif dtype == "CIRCLE":
            center = entity.dxf.center
            radius = entity.dxf.radius
            points = []
            for i in range(32):
                angle = 2 * math.pi * i / 32
                x = center.x + radius * math.cos(angle)
                y = center.y + radius * math.sin(angle)
                points.append(Vec2(x, y))
        elif dtype == "ARC":
            center = entity.dxf.center
            radius = entity.dxf.radius
            start_angle = math.radians(entity.dxf.start_angle)
            end_angle = math.radians(entity.dxf.end_angle)
            if end_angle < start_angle:
                end_angle += 2 * math.pi
            points = []
            num_points = max(16, int(abs(end_angle - start_angle) * 16 / (2 * math.pi)))
            for i in range(num_points + 1):
                angle = start_angle + (end_angle - start_angle) * i / num_points
                x = center.x + radius * math.cos(angle)
                y = center.y + radius * math.sin(angle)
                points.append(Vec2(x, y))
        elif dtype in ("TEXT", "MTEXT"):
            insert_point = entity.dxf.insert
            points = [Vec2(insert_point.x, insert_point.y)]
        elif dtype == "INSERT":
            insert_point = entity.dxf.insert
            points = [Vec2(insert_point.x, insert_point.y)]
        elif dtype == "POINT":
            location = entity.dxf.location
            points = [Vec2(location.x, location.y)]
        elif dtype == "SPLINE":
            points = []
            if hasattr(entity, 'control_points') and entity.control_points:
                for cp in entity.control_points:
                    if hasattr(cp, 'x') and hasattr(cp, 'y'):
                        points.append(Vec2(cp.x, cp.y))
                    elif isinstance(cp, (list, tuple)) and len(cp) >= 2:
                        points.append(Vec2(float(cp[0]), float(cp[1])))
            if not points and hasattr(entity, 'fit_points') and entity.fit_points:
                for fp in entity.fit_points:
                    if hasattr(fp, 'x') and hasattr(fp, 'y'):
                        points.append(Vec2(fp.x, fp.y))
                    elif isinstance(fp, (list, tuple)) and len(fp) >= 2:
                        points.append(Vec2(float(fp[0]), float(fp[1])))
        elif dtype == "ELLIPSE":
            center = entity.dxf.center
            major_axis = entity.dxf.major_axis
            ratio = getattr(entity.dxf, 'ratio', 1.0)
            major_length = math.sqrt(major_axis.x**2 + major_axis.y**2)
            minor_length = major_length * ratio
            rotation = math.atan2(major_axis.y, major_axis.x)
            points = []
            for i in range(32):
                angle = 2 * math.pi * i / 32
                x_local = major_length * math.cos(angle)
                y_local = minor_length * math.sin(angle)
                x = center.x + x_local * math.cos(rotation) - y_local * math.sin(rotation)
                y = center.y + x_local * math.sin(rotation) + y_local * math.cos(rotation)
                points.append(Vec2(x, y))
        elif dtype == "HATCH":
            points = []
            if hasattr(entity, 'paths') and entity.paths:
                for path in entity.paths:
                    if hasattr(path, 'vertices') and path.vertices:
                        for vertex in path.vertices:
                            if hasattr(vertex, 'x') and hasattr(vertex, 'y'):
                                points.append(Vec2(vertex.x, vertex.y))
                            elif isinstance(vertex, (list, tuple)) and len(vertex) >= 2:
                                points.append(Vec2(float(vertex[0]), float(vertex[1])))

        # Transform points if transformation matrix is provided
        if points and mat:
            transformed_points = []
            for p in points:
                if hasattr(mat, 'transform'):
                    transformed = mat.transform(p)
                    transformed_points.append(transformed)
                else:
                    transformed_points.append(p)
            return transformed_points
        return points
    except Exception as e:
        print(f"Warning: Failed to extract points from {entity.dxftype()}: {str(e)}")
        return []


def entity_to_geometry(entity, mat, tolerance=1e-6):
    """Convert DXF entity to Shapely geometry"""
    pts = get_entity_points(entity, mat)
    if not pts:
        return None
    
    coords = [(p.x, p.y) for p in pts]
    dtype = entity.dxftype()
    
    # Remove duplicate consecutive points
    filtered_coords = []
    for coord in coords:
        if not filtered_coords or (abs(coord[0] - filtered_coords[-1][0]) > tolerance or
                                 abs(coord[1] - filtered_coords[-1][1]) > tolerance):
            filtered_coords.append(coord)
    coords = filtered_coords
    
    if not coords:
        return None
    
    # Determine if entity should be closed
    is_closed = False
    if dtype == "LWPOLYLINE":
        is_closed = entity.closed
    elif dtype == "POLYLINE":
        is_closed = entity.is_closed
    elif dtype in ("CIRCLE", "ELLIPSE", "HATCH"):
        is_closed = True

    try:
        # Try to create polygon for closed entities
        if len(coords) >= 3 and is_closed:
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            poly = Polygon(coords)
            if poly.is_valid and poly.area > tolerance:
                return poly

        # Create line for open entities or failed polygons
        if len(coords) >= 2:
            line = LineString(coords)
            if line.is_valid and line.length > tolerance:
                return line
        elif len(coords) == 1:
            return Point(coords[0])
    except Exception as e:
        print(f"Warning: Failed to create geometry: {str(e)}")
        # Fallback to point
        if coords:
            return Point(coords[0])
    return None


def is_entity_in_room(room_geom, entity_geom, buffer_distance=50, partial_threshold=0.15):
    """Check if entity belongs to a room with overlap scoring"""
    try:
        if not room_geom or not entity_geom:
            return False, 0, "invalid_geometry"
        
        # Direct intersection test
        if room_geom.intersects(entity_geom):
            intersection = room_geom.intersection(entity_geom)
            
            # Area-based overlap
            if hasattr(intersection, 'area') and intersection.area > 1e-10:
                entity_area = getattr(entity_geom, 'area', 0)
                if entity_area > 1e-10:
                    overlap_ratio = intersection.area / entity_area
                    if overlap_ratio >= partial_threshold:
                        return True, overlap_ratio * 0.95, f"area_intersection({overlap_ratio:.3f})"
            
            # Length-based overlap
            elif hasattr(intersection, 'length') and intersection.length > 1e-10:
                entity_length = getattr(entity_geom, 'length', 0)
                if entity_length > 1e-10:
                    overlap_ratio = intersection.length / entity_length
                    if overlap_ratio >= partial_threshold:
                        return True, overlap_ratio * 0.9, f"length_intersection({overlap_ratio:.3f})"
            
            # Point containment
            elif hasattr(entity_geom, 'x') and hasattr(entity_geom, 'y'):
                if room_geom.contains(entity_geom):
                    return True, 1.0, "point_contained"
        
        return False, 0, "no_relationship"
    except Exception as e:
        print(f"Warning: Error in entity-room relationship detection: {str(e)}")
        return False, 0, "error"


def clean_room_name(room_name):
    """Clean room name by removing dimensions and extra whitespace"""
    if not room_name:
        return room_name
    
    # Remove dimension patterns
    cleaned = re.sub(r'\d+\s*[Xx]\s*\d+', '', room_name)
    cleaned = re.sub(r'\d+\'\s*\d*"\s*[Xx]\s*\d+\'\s*\d*"', '', cleaned)
    
    # Remove standalone dimension lines
    lines = cleaned.split('\n')
    filtered_lines = []
    for line in lines:
        line = line.strip()
        if not re.match(r'^\d+\s*[Xx]\s*\d+$', line) and not re.match(r'^\d+\'\s*\d*"\s*[Xx]\s*\d+\'\s*\d*"$', line):
            if line:
                filtered_lines.append(line)
    
    return filtered_lines[0].strip() if filtered_lines else room_name.strip()


def get_text_content(entity):
    """Extract text content from TEXT or MTEXT entities"""
    try:
        if entity.dxftype() == "TEXT":
            return entity.dxf.text.strip()
        elif entity.dxftype() == "MTEXT":
            return entity.plain_text().strip()
    except:
        return ""
    return ""


def extract_insert_or_geom(entity, doc):
    """Get the insert point or midpoint from geometry"""
    # First try direct insert point
    insert = entity.get("insert")
    if insert and isinstance(insert, (tuple, list)) and len(insert) >= 2:
        return insert
    
    # Try to extract from original DXF entity object
    if "entity" in entity:
        dxfe = entity["entity"]
        try:
            if hasattr(dxfe.dxf, "insert"):
                pt = dxfe.dxf.insert
                return (round(pt.x, 3), round(pt.y, 3))
            elif hasattr(dxfe.dxf, "location"):
                loc = dxfe.dxf.location
                return (round(loc.x, 3), round(loc.y, 3))
            elif hasattr(dxfe.dxf, "start"):
                start = dxfe.dxf.start
                return (round(start.x, 3), round(start.y, 3))
            elif hasattr(dxfe.dxf, "center"):
                center = dxfe.dxf.center
                return (round(center.x, 3), round(center.y, 3))
        except Exception as e:
            print(f"⚠️ DXF entity extract error: {e}")
    
    # Try geometry bounds
    geom = entity.get("geom")
    if geom:
        try:
            from shapely.geometry import shape
            bounds = shape(geom).bounds  # (minx, miny, maxx, maxy)
            mid_x = (bounds[0] + bounds[2]) / 2
            mid_y = (bounds[1] + bounds[3]) / 2
            return (round(mid_x, 3), round(mid_y, 3))
        except Exception as e:
            print(f"⚠️ Midpoint error from geom: {e}")
    
    return None


def find_room_containing_point(rooms, point):
    """Find room containing a specific point"""
    pt = Point(point)
    for room in rooms:
        if "geom" in room:
            try:
                room_poly = room["geom"]
                if room_poly.contains(pt):
                    return room.get("name", "Unnamed Room")
            except Exception as e:
                print(f"⚠️ Room geometry error: {e}")
    return None


def find_fallback_room_fixed(all_rooms, door_point):
    """Enhanced fallback room finder with coordinate system validation"""
    if not all_rooms or not door_point:
        return None
    
    print(f"🔍 DEBUG: Fallback search for door at {door_point}")
    fallback_room = None
    min_dist = float('inf')
    
    for idx, room in enumerate(all_rooms):
        try:
            # Get room geometry
            room_geom = room.get("polygon") or room.get("geom")
            if room_geom is None:
                continue
            
            # Get transformation matrix if available
            matrix = room.get("transform")
            
            # Apply transformation if needed
            if matrix is not None:
                try:
                    room_geom = transform_room_geometry(room_geom, matrix)
                except Exception as e:
                    print(f"🔍 DEBUG: Fallback transform failed for room {idx}: {e}")
                    continue
            
            if room_geom and hasattr(room_geom, 'centroid') and room_geom.is_valid:
                # Calculate distance using centroids for fallback
                centroid = room_geom.centroid
                dist = ((door_point[0] - centroid.x)**2 + (door_point[1] - centroid.y)**2)**0.5
                
                # Validate coordinate ranges to detect transformation issues
                door_x, door_y = door_point
                centroid_x, centroid_y = centroid.x, centroid.y
                
                # Check if coordinates are in similar ranges
                x_ratio = abs(door_x) / max(abs(centroid_x), 1)
                y_ratio = abs(door_y) / max(abs(centroid_y), 1)
                
                # Skip if coordinate ranges are vastly different
                if (x_ratio > 1000 or x_ratio < 0.001 or
                    y_ratio > 1000 or y_ratio < 0.001):
                    print(f"🔍 DEBUG: Skipping room {idx} due to coordinate mismatch")
                    print(f"  Door: ({door_x:.2f}, {door_y:.2f})")
                    print(f"  Room centroid: ({centroid_x:.2f}, {centroid_y:.2f})")
                    continue
                
                if dist < min_dist:
                    min_dist = dist
                    room_name = room.get("room_name") or room.get("name") or f"Room_{idx}"
                    room_handle = room.get("boundary_handle") or room.get("handle", "No Handle")
                    fallback_room = {
                        'name': room_name,
                        'handle': room_handle,
                        'distance': round(dist, 2),
                        'centroid': (centroid_x, centroid_y),
                        'room_idx': idx
                    }
                    print(f"🔍 DEBUG: Better fallback candidate: {room_name} at distance {dist:.2f}")
        except Exception as e:
            print(f"🔍 DEBUG: Error in fallback for room {idx}: {e}")
            continue
    
    return fallback_room


def extract_room_boundary_coordinates(entity, transform=None):
    """Extract room boundary coordinates for rectangles/polylines"""
    try:
        points = []
        if entity.dxftype() == "LWPOLYLINE":
            for point in entity.get_points():
                points.append((point[0], point[1]))
        elif entity.dxftype() == "POLYLINE":
            for vertex in entity.vertices:
                points.append((vertex.dxf.location[0], vertex.dxf.location[1]))
        elif entity.dxftype() == "RECTANGLE" or entity.dxftype() == "SOLID":
            if hasattr(entity.dxf, 'insert'):
                insert = entity.dxf.insert
                width = getattr(entity.dxf, 'width', 0)
                height = getattr(entity.dxf, 'height', 0)
                points = [
                    (insert[0], insert[1]),
                    (insert[0] + width, insert[1]),
                    (insert[0] + width, insert[1] + height),
                    (insert[0], insert[1] + height)
                ]
        
        if transform is not None and points:
            transformed_points = []
            for point in points:
                temp_point = [point[0], point[1], 0, 1]
                transformed = transform @ temp_point
                transformed_points.append((transformed[0], transformed[1]))
            points = transformed_points

        if len(points) >= 4:  # Rectangle should have at least 4 points
            x_coords = [p[0] for p in points]
            y_coords = [p[1] for p in points]
            min_x, max_x = min(x_coords), max(x_coords)
            min_y, max_y = min(y_coords), max(y_coords)
            center_x = (min_x + max_x) / 2
            center_y = (min_y + max_y) / 2
            
            return {
                "handle": entity.dxf.handle,
                "layer": entity.dxf.layer,
                "points": [(round(p[0], 3), round(p[1], 3)) for p in points],
                "bbox": {
                    "min_x": round(min_x, 3),
                    "max_x": round(max_x, 3),
                    "min_y": round(min_y, 3),
                    "max_y": round(max_y, 3)
                },
                "center": (round(center_x, 3), round(center_y, 3)),
                "width": round(max_x - min_x, 3),
                "height": round(max_y - min_y, 3)
            }
    except Exception as e:
        print(f"❌ Error in extract_room_boundary_coordinates: {e}")
    return None


def point_to_rectangle_distance(point, rect_data):
    """Calculate minimum distance from a point to a rectangle"""
    px, py = point
    bbox = rect_data["bbox"]
    
    # If point is inside rectangle, distance is 0
    if (bbox["min_x"] <= px <= bbox["max_x"] and
        bbox["min_y"] <= py <= bbox["max_y"]):
        return 0.0
    
    # Calculate distance to closest edge
    dx = max(bbox["min_x"] - px, 0, px - bbox["max_x"])
    dy = max(bbox["min_y"] - py, 0, py - bbox["max_y"])
    return math.sqrt(dx*dx + dy*dy)


def find_nearest_room_boundary(door_midpoint, room_boundaries):
    """Find the nearest room boundary to a door midpoint"""
    if not room_boundaries:
        return None
    
    min_distance = float('inf')
    nearest_room = None
    
    for room in room_boundaries:
        distance = point_to_rectangle_distance(door_midpoint, room)
        if distance < min_distance:
            min_distance = distance
            nearest_room = room
    
    return {
        "room": nearest_room,
        "distance": round(min_distance, 3)
    }


def get_entities_inside_room_boundary(room_boundary, all_entities, doc):
    """Get all entities that fall within a room boundary"""
    if not room_boundary or not all_entities:
        return []
    
    entities_inside = []
    bbox = room_boundary["bbox"]
    
    for entity in all_entities:
        try:
            entity_point = extract_insert_or_geom(entity, doc)
            if entity_point:
                px, py = entity_point
                # Check if point is inside room boundary
                if (bbox["min_x"] <= px <= bbox["max_x"] and
                    bbox["min_y"] <= py <= bbox["max_y"]):
                    entities_inside.append(entity)
        except Exception:
            continue
    
    return entities_inside


def determine_room_type_from_boundary(room_boundary, all_entities, doc, all_rooms=None):
    """Determine room type based on entities inside the room boundary"""
    entities_inside = get_entities_inside_room_boundary(room_boundary, all_entities, doc)
    if not entities_inside:
        return "UNKNOWN"
    
    # Calculate room area from boundary
    room_area = room_boundary["width"] * room_boundary["height"]
    
    # Use the same logic as the main function to determine room type
    room_type = determine_room_type_by_entities_ultra_fixed(
        entities_inside,
        room_area=room_area,
        all_rooms=all_rooms,
        doc=doc,
        all_entities=all_entities
    )
    return room_type if room_type else "UNKNOWN"


def get_room_boundaries_from_doc(doc):
    """Extract all room boundaries from the document"""
    room_boundaries = []
    
    # Search in modelspace
    msp = doc.modelspace()
    for entity in msp.query('LWPOLYLINE POLYLINE RECTANGLE SOLID'):
        layer = entity.dxf.layer.strip().upper()
        if "A-ROOM" in layer and "BOUNDARY" in layer:
            room_data = extract_room_boundary_coordinates(entity, None)
            if room_data:
                room_boundaries.append(room_data)
    
    # Search in blocks
    for block_def in doc.blocks:
        if not block_def.name.startswith('*'):  # Skip system blocks
            for entity in block_def:
                if entity.dxftype() in ['LWPOLYLINE', 'POLYLINE', 'RECTANGLE', 'SOLID']:
                    layer = getattr(entity.dxf, 'layer', '').strip().upper()
                    if "A-ROOM" in layer and "BOUNDARY" in layer:
                        room_data = extract_room_boundary_coordinates(entity, None)
                        if room_data:
                            room_boundaries.append(room_data)
    
    return room_boundaries

def determine_room_type_by_entities_ultra_fixed(entities_inside, room_area=None, all_rooms=None, doc=None, all_entities=None):
    """Determine room type based on entities present with improved toilet detection"""
    layer_names = [entity["layer"] for entity in entities_inside]
    
    # Bedroom detection
    if "A-Bed Furniture" in layer_names or "A-Bed" in layer_names:
        if "A-Study Table" in layer_names:
            rooms_with_bedside = []
            if all_rooms:
                for i, room_data in enumerate(all_rooms):
                    room_entities = room_data.get("entities_inside", [])
                    room_layers = [entity["layer"] for entity in room_entities]
                    if "A-Study Table" in room_layers and ("A-Bed Furniture" in room_layers or "A-Bed" in room_layers):
                        rooms_with_bedside.append((i, room_data))
                
                if len(rooms_with_bedside) == 1:
                    return "KBR"
                elif len(rooms_with_bedside) == 2:
                    room1_area = rooms_with_bedside[0][1].get("area", 0)
                    room2_area = rooms_with_bedside[1][1].get("area", 0)
                    return "KBR-01" if room_area == max(room1_area, room2_area) else "KBR-02"
                else:
                    return "KBR"
        else:
            if all_rooms and room_area:
                bedroom_areas = []
                for room_data in all_rooms:
                    room_entities = room_data.get("entities_inside", [])
                    room_layers = [entity["layer"] for entity in room_entities]
                    if "A-Bed Furniture" in room_layers or "A-Bed" in room_layers:
                        bedroom_areas.append(room_data.get("area", 0))
                
                if bedroom_areas:
                    max_bedroom_area = max(bedroom_areas)
                    return "MBR" if room_area == max_bedroom_area else "GBR"
            return "MBR"
    
    # Other room types
    if "A-Dining Table" in layer_names:
        return "LIVING AND DINING"
    elif "A-1S Sofa" in layer_names:
        return "GREEN DECK"
    elif "A-Refrigerator" in layer_names or "A-Fridge" in layer_names:
        return "KITCHEN"
    elif "A-3S Sofa" in layer_names and "A-TV" in layer_names:
        rooms_with_3s_tv = []
        if all_rooms:
            for i, room_data in enumerate(all_rooms):
                room_entities = room_data.get("entities_inside", [])
                room_layers = [entity["layer"] for entity in room_entities]
                if "A-TV" in room_layers and "A-3S Sofa" in room_layers:
                    rooms_with_3s_tv.append((i, room_data))
            
            if len(rooms_with_3s_tv) == 1:
                return "LIVING"
            elif len(rooms_with_3s_tv) == 2:
                room1_area = rooms_with_3s_tv[0][1].get("area", 0)
                room2_area = rooms_with_3s_tv[1][1].get("area", 0)
                return "LIVING" if room_area == max(room1_area, room2_area) else "DRAWING"
            else:
                return "LIVING"
    
    # Enhanced toilet detection with nearest room identification
    if "A-Handwash" in layer_names or "A-WC" in layer_names:
        if "A-Door Tag" in layer_names:
            for entity in entities_inside:
                if entity["layer"] == "A-Door Tag":
                    # Extract door tag coordinates
                    tag_point = extract_insert_or_geom(entity, doc)
                    if tag_point:
                        # Find nearest door lineblock_doors = find_door_midpoints_in_block(docblock_doors = find_door_midpoints_in_block(doc, "UNIT-1")
                        block_doors = find_door_midpoints_in_block(doc)
                        direct_doors = find_direct_door_lines(doc)
                        all_door_lines = block_doors + direct_doors

                        min_distance = float('inf')
                        nearest_door_line = None

                        for door_data in all_door_lines:
                            door_midpoint = door_data["midpoint"]
                            dx = door_midpoint[0] - tag_point[0]
                            dy = door_midpoint[1] - tag_point[1]
                            distance = (dx ** 2 + dy ** 2) ** 0.5
                            if distance < min_distance:
                                min_distance = distance
                                nearest_door_line = {
                                    "handle": door_data["handle"],
                                    "distance": distance,
                                    "midpoint": door_midpoint,
                                    "layer": door_data["layer"]
                                }

                        if nearest_door_line:
                            door_point = nearest_door_line["midpoint"]
                            # Find nearest room boundary to the door
                            room_boundaries = get_room_boundaries_from_doc(doc)
                            nearest_room_data = find_nearest_room_boundary(door_point, room_boundaries)

                            # Build the return string
                            result_str = (f"TOILET (Door Tag: ({tag_point[0]:.2f}, {tag_point[1]:.2f}), "
                                        f"Door Line: ({door_point[0]:.2f}, {door_point[1]:.2f}), "
                                        f"Tag-to-Door Distance: {nearest_door_line['distance']:.2f}, "
                                        f"Door Handle: {nearest_door_line['handle']}")

                            if nearest_room_data and nearest_room_data["room"]:
                                room = nearest_room_data["room"]
                                room_handle = room.get("handle", "N/A")

                                # Find the actual room from all_rooms that matches this boundary
                                nearest_room_info = None
                                for room_data in all_rooms:
                                    if room_data.get("boundary_handle") == room_handle:
                                        nearest_room_info = room_data
                                        break

                                if nearest_room_info:
                                    # Get the room name from the actual room data
                                    room_name = nearest_room_info.get("room_name", "Unknown")
                                    
                                    # If room_name is still generic, try to determine it from entities
                                    if room_name in ["Unknown", f"Room_{nearest_room_info.get('room_idx', 0)}"]:
                                        room_entities = nearest_room_info.get("entities_inside", [])
                                        if room_entities:
                                            determined_type = determine_room_type_by_entities_ultra_fixed(
                                                room_entities,
                                                nearest_room_info.get("area", 0),
                                                all_rooms,
                                                doc,
                                                all_entities
                                            )
                                            if determined_type and not determined_type.startswith("TOILET"):
                                                room_name = determined_type
                                    
                                    # Determine room type from boundary entities
                                    room_type = determine_room_type_from_boundary(room, all_entities, doc, all_rooms)
                                    
                                    # Create toilet name based on nearest room
                                    toilet_name = f"{room_name} TOILET" if room_name != "Unknown" else "TOILET"
                                    
                                    result_str = (f"{toilet_name} ")
                                else:
                                    # Fallback: try to determine room type from boundary
                                    room_type = determine_room_type_from_boundary(room, all_entities, doc, all_rooms)
                                    toilet_name = f"{room_type} TOILET" if room_type != "UNKNOWN" else "TOILET"
                                    
                                    result_str = (f"{toilet_name} (Door Tag: ({tag_point[0]:.2f}, {tag_point[1]:.2f}), "
                                                f"Door Line: ({door_point[0]:.2f}, {door_point[1]:.2f}), "
                                                f"Tag-to-Door Distance: {nearest_door_line['distance']:.2f}, "
                                                f"Door Handle: {nearest_door_line['handle']}, "
                                                f"Nearest Room: ({room['center'][0]:.2f}, {room['center'][1]:.2f}), "
                                                f"Room Type: {room_type}, "
                                                f"Room Size: {room['width']:.2f}x{room['height']:.2f}, "
                                                f"Door-to-Room Distance: {nearest_room_data['distance']:.2f}, "
                                                f"Room Handle: {room_handle})")
                            else:
                                result_str += ", No room boundary found)"

                            return result_str
                        else:
                            return f"TOILET (Door Tag: ({tag_point[0]:.2f}, {tag_point[1]:.2f}), No door line found)"
                    else:
                        return "TOILET (Door tag found but coordinates not extracted)"
        else:
            return "TOILET"
    
    return None


def get_room_name_for_toilet(all_rooms, room_handle):
    """Helper function to get room name for toilet naming"""
    for room_data in all_rooms:
        if room_data.get("boundary_handle") == room_handle:
            # First try to get the already determined room name
            room_name = room_data.get("room_name", "Unknown")
            
            # If it's still generic, try to determine from entities
            if room_name in ["Unknown", f"Room_{room_data.get('room_idx', 0)}"]:
                room_entities = room_data.get("entities_inside", [])
                if room_entities:
                    # Try to determine room type from entities
                    entity_layers = [entity["layer"] for entity in room_entities]
                    
                    # Simple room type determination for toilet naming
                    if "A-Bed Furniture" in entity_layers or "A-Bed" in entity_layers:
                        return "BEDROOM"
                    elif "A-3S Sofa" in entity_layers and "A-TV" in entity_layers:
                        return "LIVING"
                    elif "A-Dining Table" in entity_layers:
                        return "DINING"
                    elif "A-Refrigerator" in entity_layers or "A-Fridge" in entity_layers:
                        return "KITCHEN"
                    elif "A-1S Sofa" in entity_layers:
                        return "GREEN DECK"
            
            return room_name
    
    return "Unknown"


# Alternative simpler approach - just for toilet detection
def determine_room_type_by_entities_simple_toilet(entities_inside, room_area=None, all_rooms=None, doc=None, all_entities=None):
    """Simplified version focused on better toilet detection"""
    layer_names = [entity["layer"] for entity in entities_inside]
    
    # Toilet detection with simplified naming
    if "A-Handwash" in layer_names or "A-WC" in layer_names:
        if "A-Door Tag" in layer_names:
            for entity in entities_inside:
                if entity["layer"] == "A-Door Tag":
                    tag_point = extract_insert_or_geom(entity, doc)
                    if tag_point:
                        # Find nearest door and room
                        block_doors = find_door_midpoints_in_block(doc, block_name=None)
                        direct_doors = find_direct_door_lines(doc)
                        all_door_lines = block_doors + direct_doors

                        min_distance = float('inf')
                        nearest_door_line = None

                        for door_data in all_door_lines:
                            door_midpoint = door_data["midpoint"]
                            dx = door_midpoint[0] - tag_point[0]
                            dy = door_midpoint[1] - tag_point[1]
                            distance = (dx ** 2 + dy ** 2) ** 0.5
                            if distance < min_distance:
                                min_distance = distance
                                nearest_door_line = door_data

                        if nearest_door_line:
                            door_point = nearest_door_line["midpoint"]
                            room_boundaries = get_room_boundaries_from_doc(doc)
                            nearest_room_data = find_nearest_room_boundary(door_point, room_boundaries)

                            if nearest_room_data and nearest_room_data["room"]:
                                room = nearest_room_data["room"]
                                room_handle = room.get("handle", "N/A")
                                
                                # Find the actual room name
                                nearest_room_name = get_room_name_for_toilet(all_rooms, room_handle)
                                
                                # Create appropriate toilet name
                                if nearest_room_name and nearest_room_name != "Unknown":
                                    if nearest_room_name in ["MBR", "GBR", "KBR", "KBR-01", "KBR-02"]:
                                        toilet_name = f"{nearest_room_name} TOILET"
                                    elif "BEDROOM" in nearest_room_name.upper():
                                        toilet_name = f"{nearest_room_name} TOILET"
                                    elif nearest_room_name in ["LIVING", "LIVING AND DINING"]:
                                        toilet_name = "COMMON TOILET"
                                    else:
                                        toilet_name = f"{nearest_room_name} TOILET"
                                else:
                                    toilet_name = "TOILET"
                                
                                return toilet_name
                            else:
                                return "TOILET"
                        else:
                            return "TOILET"
                    else:
                        return "TOILET"
        else:
            return "TOILET"
 
    
    return None

def transform_room_geometry(room_geom, matrix):
    """Apply transformation matrix to room geometry"""
    if not matrix or len(matrix) < 6:
        return room_geom
    
    try:
        a, b, c, d, e, f = matrix[:6]
        transformed_geom = affine_transform(room_geom, [a, b, c, d, e, f])
        
        if transformed_geom.is_valid and not transformed_geom.is_empty:
            return transformed_geom
        else:
            print(f"⚠️ Transformation resulted in invalid geometry, using original")
            return room_geom
    except Exception as e:
        print(f"⚠️ Transformation failed: {e}, using original geometry")
        return room_geom


def extract_all_entities(doc, block_name, mat=Matrix44(), depth=0, max_depth=10):
    """Extract all entities from a DXF block recursively"""
    if depth > max_depth:
        print(f"Warning: Max depth ({max_depth}) reached for block: {block_name}")
        return []
    
    all_entities = []
    
    if block_name not in doc.blocks:
        print(f"Warning: Block '{block_name}' not found in document")
        return all_entities
    
    try:
        block = doc.blocks[block_name]
        entity_count = 0
        
        for entity in block:
            entity_count += 1
            entity_handle = getattr(entity.dxf, 'handle', f'unknown_{id(entity)}_{entity_count}')
            entity_type = entity.dxftype()
            
            if entity_type == "INSERT":
                # Handle INSERT entities (block references)
                insert_point = getattr(entity.dxf, 'insert', Vec3(0, 0, 0))
                rotation = getattr(entity.dxf, 'rotation', 0)
                xscale = getattr(entity.dxf, 'xscale', 1)
                yscale = getattr(entity.dxf, 'yscale', 1)
                zscale = getattr(entity.dxf, 'zscale', 1)
                
                sub_mat = Matrix44.chain(
                    mat,
                    Matrix44.translate(insert_point.x, insert_point.y, insert_point.z),
                    Matrix44.z_rotate(math.radians(rotation)),
                    Matrix44.scale(xscale, yscale, zscale),
                )
                
                # Recursively extract from sub-block
                sub_block_name = getattr(entity.dxf, 'name', '')
                if sub_block_name:
                    sub_entities = extract_all_entities(doc, sub_block_name, sub_mat, depth + 1, max_depth)
                    all_entities.extend(sub_entities)
                
                # Also add the INSERT entity itself
                all_entities.append((entity, mat, entity_handle, depth))
            else:
                all_entities.append((entity, mat, entity_handle, depth))
        
        print(f"Extracted {len(all_entities)} entities from block '{block_name}' at depth {depth}")
        
    except Exception as e:
        print(f"Error accessing block '{block_name}': {str(e)}")
    
    return all_entities


def process_block_entities(block_def, transform, doc, door_data_list, level=0):
    """Process entities in a block with proper transformation"""
    indent = "  " * level
    print(f"{indent}🔍 Processing block with {len(list(block_def))} entities")
    
    for entity in block_def:
        try:
            entity_layer = getattr(entity.dxf, 'layer', 'N/A')
            print(f"{indent}📄 Entity: {entity.dxftype()} | Layer: {entity_layer} | Handle: {entity.dxf.handle}")
            
            if entity.dxftype() == "INSERT":
                # Handle nested blocks
                nested_block_name = entity.dxf.name
                print(f"{indent}↪️ Entering nested block: {nested_block_name}")
                
                nested_transform = create_transform_matrix(entity)
                if nested_transform is not None:
                    # Combine transformations
                    if transform is not None:
                        combined_transform = transform @ nested_transform
                    else:
                        combined_transform = nested_transform
                else:
                    combined_transform = transform
                
                if nested_block_name in [block.name for block in doc.blocks]:
                    nested_block_def = doc.blocks[nested_block_name]
                    process_block_entities(nested_block_def, combined_transform, doc, door_data_list, level + 1)
                else:
                    print(f"{indent}❌ Block '{nested_block_name}' not found in doc.blocks")
            
            elif entity.dxftype() == "LINE":
                # Check if this is a door line
                layer = entity_layer.strip().upper()
                if "DOOR" in layer and "LINE" in layer:
                    door_data = extract_door_line_coordinates(entity, doc, transform)
                    if door_data:
                        print(f"{indent}✅ Door line found | Handle: {door_data['handle']} | Mid: {door_data['midpoint']}")
                        door_data_list.append(door_data)
                        
        except Exception as e:
            print(f"{indent}⚠️ Error processing entity: {e}")


def create_transform_matrix(insert_entity):
    """Create transformation matrix using ezdxf's Matrix44"""
    try:
        # Get insert properties
        insert_point = insert_entity.dxf.insert
        scale_x = insert_entity.dxf.get("xscale", 1.0)
        scale_y = insert_entity.dxf.get("yscale", 1.0)
        scale_z = insert_entity.dxf.get("zscale", 1.0)
        rotation = insert_entity.dxf.get("rotation", 0.0)
        
        # Create transformation matrix
        matrix = Matrix44()
        # Apply scaling
        matrix = matrix.scale(scale_x, scale_y, scale_z)
        # Apply rotation around Z-axis
        matrix = matrix.rotate_z(rotation)
        # Apply translation
        matrix = matrix.translate(insert_point[0], insert_point[1], insert_point[2] if len(insert_point) > 2 else 0)
        
        print(f"🔧 INSERT Transform - Pos: {insert_point}, Rot: {math.degrees(rotation):.1f}°, Scale: ({scale_x}, {scale_y})")
        return matrix
        
    except Exception as e:
        print(f"❌ Error creating transform matrix: {e}")
        return None


def extract_door_line_coordinates(entity, doc=None, mat=None):
    """Extract door line coordinates with proper transformation"""
    try:
        if entity.dxftype() == "LINE" and hasattr(entity.dxf, "start") and hasattr(entity.dxf, "end"):
            start_pt = entity.dxf.start
            end_pt = entity.dxf.end
            
            # If we have a transform, apply it using ezdxf's built-in transformation
            if mat is not None:
                entity_copy = entity.copy()
                entity_copy.transform(mat)
                start_pt = entity_copy.dxf.start
                end_pt = entity_copy.dxf.end
            
            # Calculate midpoint
            mid_x = (start_pt[0] + end_pt[0]) / 2
            mid_y = (start_pt[1] + end_pt[1]) / 2
            
            return {
                "handle": entity.dxf.handle,
                "start": (round(start_pt[0], 3), round(start_pt[1], 3)),
                "end": (round(end_pt[0], 3), round(end_pt[1], 3)),
                "midpoint": (round(mid_x, 3), round(mid_y, 3)),
                "layer": entity.dxf.layer
            }
            
    except Exception as e:
        print(f"❌ Error in extract_door_line_coordinates: {e}")
        return None


def find_direct_door_lines(doc):
    """Find door lines directly in modelspace"""
    msp = doc.modelspace()
    door_data_list = []
    
    print("🔍 Searching for direct door lines in modelspace")
    
    # Search for lines with door-related layers
    for entity in msp.query('LINE'):
        layer = entity.dxf.layer.strip().upper()
        if "DOOR" in layer and "LINE" in layer:
            door_data = extract_door_line_coordinates(entity, doc, None)  # No transform for direct lines
            if door_data:
                print(f"🟢 Direct Door | Handle: {door_data['handle']} | Mid: {door_data['midpoint']}")
                door_data_list.append(door_data)
    
    return door_data_list


def find_door_midpoints_in_block(doc, block_name=None):
    """Find door midpoints in all UNIT blocks or a specific block"""
    msp = doc.modelspace()
    door_data_list = []
    
    if block_name:
        # Search for specific block
        target_blocks = [block_name]
    else:
        # Search for all UNIT-* blocks
        target_blocks = []
        for insert in msp.query("INSERT"):
            if insert.dxf.name.startswith('UNIT-'):
                if insert.dxf.name not in target_blocks:
                    target_blocks.append(insert.dxf.name)
    
    print(f"🔍 Searching for INSERT entities of blocks: {target_blocks}")
    
    for block_name in target_blocks:
        inserts_found = 0
        for insert in msp.query("INSERT"):
            if insert.dxf.name.strip().upper() == block_name.upper():
                inserts_found += 1
                print(f"📦 Found INSERT #{inserts_found} of block '{block_name}' at {insert.dxf.insert}")
                
                # Get the block definition
                block_def = None
                for block in doc.blocks:
                    if block.name == block_name:
                        block_def = block
                        break
                
                if block_def:
                    transform = create_transform_matrix(insert)
                    process_block_entities(block_def, transform, doc, door_data_list)
                else:
                    print(f"❌ Block definition '{block_name}' not found")
        
        if inserts_found == 0:
            print(f"⚠️ No INSERT entities found for block '{block_name}'")
    
    return door_data_list


def assign_entities_to_rooms(rooms, insert_entities, room_boundary_handles):
    """Assign entities to rooms based on spatial relationships"""
    assignment_stats = {
        "total_entities": 0,
        "assigned_entities": 0,
        "unassigned_entities": 0,
        "multiple_assignments": 0,
        "layer_stats": {}
    }
    unassigned_entities = []
    
    # First pass: Standard assignment
    for entity, mat, handle, depth in insert_entities:
        assignment_stats["total_entities"] += 1
        
        if handle in room_boundary_handles:
            continue
        
        layer_name = entity.dxf.layer.strip()
        
        if layer_name not in assignment_stats["layer_stats"]:
            assignment_stats["layer_stats"][layer_name] = {"total": 0, "assigned": 0, "unassigned": 0}
        assignment_stats["layer_stats"][layer_name]["total"] += 1
        
        # Convert entity to geometry
        geom = entity_to_geometry(entity, mat)
        if not geom:
            assignment_stats["unassigned_entities"] += 1
            assignment_stats["layer_stats"][layer_name]["unassigned"] += 1
            unassigned_entities.append({
                "handle": handle,
                "layer": layer_name,
                "type": entity.dxftype(),
                "reason": "no_geometry"
            })
            continue
        
        entity_info = {
            "layer": layer_name,
            "type": entity.dxftype(),
            "handle": handle,
            "depth": depth,
            "geometry_type": type(geom).__name__,
            "entity": entity,
            "geom": geom
        }
        
        matching_rooms = []
        
        # Test against each room
        for room_idx, room in enumerate(rooms):
            try:
                is_inside, score, method = is_entity_in_room(room["polygon"], geom)
                if is_inside and score > 0.1:
                    matching_rooms.append({
                        "room_idx": room_idx,
                        "room": room,
                        "score": score,
                        "method": method
                    })
            except Exception as e:
                print(f"Warning: Error checking entity {handle} ({layer_name}) against room {room_idx}: {str(e)}")
                continue
        
        if matching_rooms:
            assignment_stats["assigned_entities"] += 1
            assignment_stats["layer_stats"][layer_name]["assigned"] += 1
            
            if len(matching_rooms) > 1:
                assignment_stats["multiple_assignments"] += 1
                # Sort by score and assign to best match
                matching_rooms.sort(key=lambda x: x["score"], reverse=True)
                significant_matches = [room for room in matching_rooms if room["score"] > 0.2]
                
                if len(significant_matches) > 1:
                    # Multi-room entity
                    total_score = sum(room["score"] for room in significant_matches)
                    for room_match in significant_matches:
                        entity_info_multi = entity_info.copy()
                        entity_info_multi["is_multi_room"] = True
                        entity_info_multi["overlap_score"] = room_match["score"]
                        entity_info_multi["normalized_score"] = room_match["score"] / total_score
                        entity_info_multi["assignment_method"] = room_match["method"]
                        room_match["room"]["entities_inside"].append(entity_info_multi)
                else:
                    # Single best match
                    best_match = matching_rooms[0]
                    entity_info["overlap_score"] = best_match["score"]
                    entity_info["assignment_method"] = best_match["method"]
                    best_match["room"]["entities_inside"].append(entity_info)
            else:
                # Single match
                best_match = matching_rooms[0]
                entity_info["overlap_score"] = best_match["score"]
                entity_info["assignment_method"] = best_match["method"]
                best_match["room"]["entities_inside"].append(entity_info)
        else:
            assignment_stats["unassigned_entities"] += 1
            assignment_stats["layer_stats"][layer_name]["unassigned"] += 1
            unassigned_entities.append({
                "handle": handle,
                "layer": layer_name,
                "type": entity.dxftype(),
                "reason": "no_match"
            })
    
    # Second pass: Re-assign important entities with relaxed criteria
    important_layers = [
        "A-Bed Furniture", "A-TV", "A-3S Sofa", "A-Dining Table", "A-Study Table",
        "A-Refrigerator", "A-Handwash", "A-WC", "A-1S Sofa", "A-Fridge"
    ]
    
    entities_to_reassign = [ent for ent in unassigned_entities if ent["layer"] in important_layers]
    
    for unassigned in entities_to_reassign:
        target_entity = None
        for entity, mat, handle, depth in insert_entities:
            if handle == unassigned["handle"]:
                target_entity = (entity, mat, handle, depth)
                break
        
        if target_entity:
            entity, mat, handle, depth = target_entity
            layer_name = entity.dxf.layer.strip()
            geom = entity_to_geometry(entity, mat)
            
            if geom:
                best_room = None
                best_score = 0
                best_method = "none"
                
                for room_idx, room in enumerate(rooms):
                    try:
                        is_inside, score, method = is_entity_in_room(
                            room["polygon"], geom,
                            buffer_distance=75,
                            partial_threshold=0.05
                        )
                        if is_inside and score > best_score:
                            best_room = room
                            best_score = score
                            best_method = method
                    except:
                        continue
                
                if best_room and best_score > 0.05:
                    entity_info = {
                        "layer": layer_name,
                        "type": entity.dxftype(),
                        "handle": handle,
                        "depth": depth,
                        "geometry_type": type(geom).__name__,
                        "overlap_score": best_score,
                        "assignment_method": f"second_pass_{best_method}",
                        "is_important_reassignment": True,
                        "entity": entity,
                        "geom": geom
                    }
                    
                    best_room["entities_inside"].append(entity_info)
                    assignment_stats["assigned_entities"] += 1
                    assignment_stats["unassigned_entities"] -= 1
                    assignment_stats["layer_stats"][layer_name]["assigned"] += 1
                    assignment_stats["layer_stats"][layer_name]["unassigned"] -= 1
                    unassigned_entities = [ent for ent in unassigned_entities if ent["handle"] != handle]
    
    # Print statistics
    print(f"\nEntity Assignment Statistics:")
    print(f"  Total entities: {assignment_stats['total_entities']}")
    print(f"  Assigned: {assignment_stats['assigned_entities']}")
    print(f"  Unassigned: {assignment_stats['unassigned_entities']}")
    print(f"  Multi-room: {assignment_stats['multiple_assignments']}")
    
    success_rate = (assignment_stats['assigned_entities'] / max(assignment_stats['total_entities'], 1)) * 100
    print(f"  Success rate: {success_rate:.1f}%")
    
    return assignment_stats, unassigned_entities


def extract_block_text_info_for_insert(doc, block_name, mat):
    """Extract text information from a block with transformation"""
    text_info = []
    
    if block_name not in doc.blocks:
        return text_info
    
    try:
        block = doc.blocks[block_name]
        for entity in block:
            if entity.dxftype() in ("TEXT", "MTEXT"):
                try:
                    text_content = get_text_content(entity)
                    if text_content:
                        # Get position and transform it
                        pos = entity.dxf.insert
                        if mat:
                            transformed_pos = mat.transform(pos)
                        else:
                            transformed_pos = pos
                        
                        text_info.append({
                            'Text': text_content,
                            'Position': transformed_pos,
                            'Layer': entity.dxf.layer,
                            'Handle': entity.dxf.handle
                        })
                except Exception as e:
                    print(f"Warning: Error processing text entity: {e}")
                    continue
    except Exception as e:
        print(f"Warning: Error accessing block {block_name}: {e}")
    
    return text_info

def check_text_within_rooms(room_polygon, text_position, buffer_distance=10):
    try:
        text_point = Point(text_position.x, text_position.y)

        if room_polygon.contains(text_point):
            return True

        buffered_room = room_polygon.buffer(buffer_distance)
        return buffered_room.contains(text_point)

    except Exception as e:
        print(f"Warning: Error checking text position: {e}")
        return False

def analyze_multi_room_entities(rooms):
    """Analyze entities that span multiple rooms"""
    multi_room_entities = []
    
    # Create a mapping of entity handles to rooms
    entity_to_rooms = {}
    for room_idx, room in enumerate(rooms):
        for entity in room["entities_inside"]:
            handle = entity.get("handle", "")
            if handle:
                if handle not in entity_to_rooms:
                    entity_to_rooms[handle] = {
                        "entity": entity,
                        "rooms": []
                    }
                entity_to_rooms[handle]["rooms"].append({
                    "room_idx": room_idx,
                    "room_name": room["room_name"],
                    "overlap_score": entity.get("overlap_score", 0)
                })
    
    # Find entities in multiple rooms
    for handle, data in entity_to_rooms.items():
        if len(data["rooms"]) > 1:
            multi_room_entities.append(data)
    
    return multi_room_entities