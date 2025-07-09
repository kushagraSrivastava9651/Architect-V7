def is_matching_room_boundary(entity, matched_room, user_room):
    """
    Check if the entity boundary matches the room by comparing handle or dimensions
    """
    try:
        # First try handle matching (most reliable)
        room_handle = matched_room.get('Handle')
        if room_handle and hasattr(entity.dxf, 'handle') and entity.dxf.handle == room_handle:
            return True
        
        # Fallback: Compare dimensions if polygon data available
        if hasattr(entity, 'get_points') and matched_room.get('Polygon'):
            points = [p[:2] for p in entity.get_points()]
            if len(points) >= 3:
                from shapely.geometry import Polygon
                try:
                    entity_polygon = Polygon(points)
                    if entity_polygon.is_valid:
                        matched_polygon = matched_room['Polygon']
                        
                        # Compare areas with tolerance
                        area_diff = abs(entity_polygon.area - matched_polygon.area)
                        area_tolerance = matched_polygon.area * 0.05  # 5% tolerance for area
                        
                        if area_diff <= area_tolerance:
                            return True
                except:
                    pass
        
        return False
        
    except Exception as e:
        print(f"Error in boundary matching: {e}")
        return False
