# Example 1: تمثيل المعادلة الكيميائية للبناء الضوئي
# Status: verified by running it
# يقوم هذا الكود بحساب نواتج عملية البناء الضوئي بناءً على عدد مولات ثاني أكسيد الكربون والماء. نستخدم دالة بسيطة لتطبيق نسب المعادلة الكيميائية 6CO2 + 6H2O -> C6H12O6 + 6O2. يطبع الكود ناتج إنتاج 1 مول من الجلوكوز و6 مولات من الأكسجين عند توفر 6 مولات من المتفاعلات.

def calculate_photosynthesis_products(co2_moles, h2o_moles):
    if co2_moles == h2o_moles:
        glucose = co2_moles / 6
        oxygen = co2_moles
        return glucose, oxygen
    return 0, 0

glucose, oxygen = calculate_photosynthesis_products(6, 6)
print(f'Glucose produced: {glucose} mole')
print(f'Oxygen produced: {oxygen} moles')


# Example 2: محاكاة العوامل المؤثرة على معدل البناء الضوئي
# Status: verified by running it
# يوضح هذا المثال كيف تؤثر العوامل البيئية مثل شدة الضوء وتركيز ثاني أكسيد الكربون على معدل البناء الضوئي. نستخدم جملة شرطية لتحديد ما إذا كان المعدل سيزداد عند توفر ظروف مثالية. يطبع الكود قيمة المعدل النهائي بناءً على المدخلات المحددة.

def estimate_photosynthesis_rate(light_intensity, co2_level):
    base_rate = 10
    if light_intensity > 5 and co2_level > 5:
        return base_rate * 2
    return base_rate

intensity = 8
co2 = 7
rate = estimate_photosynthesis_rate(intensity, co2)
print(f'Photosynthesis rate is: {rate} units per hour')
