import time
import sys
import subprocess
import json
import re
import reverse_geocode  # pip install reverse-geocode


class PluginExifFacesLocation:
    """
    A plugin that extracts:
      - People faces (names + positions) from EXIF metadata
      - Picture location (country/state/city) from GPS coordinates using reverse_geocode
    """

    # --- Tool definition ---
    def get_tool_definition(self):
        return {
            'type': 'function',
            'function': {
                'name': 'extract_faces_and_location',
                'description': (
                    'Extracts person names, face positions, and GPS-based location from an image '
                    'using ExifTool and reverse_geocode (offline).'
                ),
                'parameters': {
                    "type": "object",
                    "properties": {
                        "image_path": {
                            "type": "string",
                            "description": "Path to the image file to analyze"
                        }
                    },
                    "required": ["image_path"]
                }
            }
        }

    # --- Helper: Convert GPS coordinates from EXIF format ---
    @staticmethod
    def _convert_gps_to_decimal(gps_value, ref=None):
        """
        Convert EXIF GPS coordinate to decimal degrees.
        Handles:
          - List format: [deg, min, sec]
          - String format: "43 deg 10' 3.05\" N"
        """
        try:
            if isinstance(gps_value, (list, tuple)):
                d, m, s = gps_value
            elif isinstance(gps_value, str):
                # Example: "43 deg 10' 3.05\" N"
                match = re.match(r"(\d+)[^\d]+(\d+)[^\d]+([\d.]+)[^\d]*(\w?)", gps_value.strip())
                if not match:
                    return None
                d, m, s, ref_in_str = match.groups()
                d, m, s = float(d), float(m), float(s)
                if ref_in_str and not ref:
                    ref = ref_in_str
            else:
                return None

            decimal = d + m / 60.0 + s / 3600.0
            if ref and ref.upper() in ["S", "W"]:
                decimal = -decimal
            return decimal
        except Exception:
            return None

    # --- Main function ---
    def extract_faces_and_location(self, image_path):
        """
        Extracts EXIF face regions and GPS-based location.
        Returns:
            {
                "faces": {...},
                "location": {...}
            }
        """
        # --- Run ExifTool and wait for completion ---
        try:
            result = subprocess.run(
                ["exiftool", "-json", image_path],
                capture_output=True,
                text=True,
                check=True,
                timeout=15
            )
            if not result.stdout.strip():
                return {"faces": {}, "location": {"latitude": None, "longitude": None, "details": "unknown location"}}
            metadata = json.loads(result.stdout)[0]
        except subprocess.TimeoutExpired:
            return {"faces": {}, "location": {"latitude": None, "longitude": None, "details": "unknown location"}}
        except subprocess.CalledProcessError as e:
            return {"faces": {}, "location": {"latitude": None, "longitude": None, "details": "unknown location"}}
        except Exception:
            return {"faces": {}, "location": {"latitude": None, "longitude": None, "details": "unknown location"}}

        # -------------------- FACE EXTRACTION --------------------
        img_w = metadata.get("ImageWidth")
        img_h = metadata.get("ImageHeight")

        region_x = metadata.get("RegionAreaX", [])
        region_y = metadata.get("RegionAreaY", [])
        region_w = metadata.get("RegionAreaW", [])
        region_h = metadata.get("RegionAreaH", [])
        persons = metadata.get("RegionPersonDisplayName", [])

        if not isinstance(persons, list):
            persons = [persons]
        if not isinstance(region_x, list):
            region_x = [region_x]
            region_y = [region_y]
            region_w = [region_w]
            region_h = [region_h]

        faces = {}
        for i, name in enumerate(persons):
            # Skip ignored or unknown faces
            if not name or name.strip().lower() in ["unknown", "ignored"]:
                continue
            try:
                x, y, w, h = float(region_x[i]), float(region_y[i]), float(region_w[i]), float(region_h[i])
            except (IndexError, ValueError):
                continue

            normalized = {"x": x, "y": y, "w": w, "h": h}
            pixels = None
            if img_w and img_h:
                pixels = {
                    "x": int(x * img_w),
                    "y": int(y * img_h),
                    "w": int(w * img_w),
                    "h": int(h * img_h),
                }

            horiz = "left" if x < 0.33 else "center" if x < 0.66 else "right"
            vert = "top" if y < 0.33 else "middle" if y < 0.66 else "bottom"
            position = f"{vert}-{horiz}"

            faces[name] = {
                "normalized": normalized,
                "pixels": pixels,
                "position": position
            }

        # -------------------- GPS LOCATION EXTRACTION --------------------
        lat, lon = None, None
        gps_lat = metadata.get("GPSLatitude") or metadata.get("GPSPosition")
        gps_lat_ref = metadata.get("GPSLatitudeRef")
        gps_lon = metadata.get("GPSLongitude")
        gps_lon_ref = metadata.get("GPSLongitudeRef")

        # Special case: GPSPosition contains both lat/lon as string "lat, lon"
        if gps_lat and isinstance(gps_lat, str) and "," in gps_lat:
            try:
                lat_str, lon_str = gps_lat.split(",")
                lat = self._convert_gps_to_decimal(lat_str.strip())
                lon = self._convert_gps_to_decimal(lon_str.strip())
            except Exception:
                lat, lon = None, None
        else:
            lat = self._convert_gps_to_decimal(gps_lat, gps_lat_ref)
            lon = self._convert_gps_to_decimal(gps_lon, gps_lon_ref)

        location_details = {}
        if lat is not None and lon is not None:
            try:
                location_info = reverse_geocode.get((lat, lon), min_population=100000)
                # Only keep the location details, filter out population and coordinates
                
                if isinstance(location_info, dict):
                    location_details = {k: v for k, v in location_info.items() if k not in ["population", "latitude", "longitude", "country_code"]}
            except Exception:
                location_details = "unknown location"

        # --- Final structured result ---
        return {
            "faces": faces,  # will be empty if no valid faces found
            "location": location_details or "unknown location"
        }
