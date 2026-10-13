# Example 1: محاكاة الخاصية الأسموزية في امتصاص الماء
# Status: verified by running it
# يوضح هذا الكود كيف تنتقل المياه من التربة إلى الجذور بناءً على تركيز الأملاح. نستخدم دالة تقارن بين تركيز الأملاح في التربة والجذر لتحديد اتجاه حركة الماء. إذا كان تركيز الجذر أعلى، ينتقل الماء للداخل. يطبع الكود النتيجة وهي Water moves into the root.

def simulate_osmosis(soil_concentration, root_concentration):
    if root_concentration > soil_concentration:
        return "Water moves into the root"
    else:
        return "No water absorption"

soil_salt = 5
root_salt = 15
result = simulate_osmosis(soil_salt, root_salt)
print(f"Result: {result}")


# Example 2: نمذجة عملية البناء الضوئي
# Status: verified by running it
# يستخدم هذا المثال البرمجة الكائنية لتمثيل عملية البناء الضوئي. نتحقق من توفر ضوء الشمس والماء وثاني أكسيد الكربون لإنتاج الجلوكوز. عند توفر الموارد، تزداد قيمة الجلوكوز في كائن النبات. يطبع الكود Plant Fern produced glucose: 10 units.

class Plant:
    def __init__(self, name):
        self.name = name
        self.glucose = 0

    def perform_photosynthesis(self, sunlight, water, co2):
        if sunlight and water > 0 and co2 > 0:
            self.glucose += 10
            return True
        return False

my_plant = Plant("Fern")
success = my_plant.perform_photosynthesis(True, 5, 5)
print(f"Plant {my_plant.name} produced glucose: {my_plant.glucose} units")
