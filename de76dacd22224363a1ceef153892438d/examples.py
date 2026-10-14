# Example 1: استخدام args و kwargs للتعامل مع المدخلات المرنة
# Status: verified by running it
# يقوم هذا المثال بتعريف دالة تقبل عدداً غير محدد من المدخلات باستخدام args لتجميع الأرقام و kwargs لتخزين المعاملات المسماة. يتم تمرير القيم الرقمية ليتم جمعها بينما يتم عرض المعاملات الإضافية كقاموس. تطبع الدالة العنوان، مجموع الأرقام وهو 60، ثم حالة التقرير والأولوية.

def summarize_data(title, *args, **kwargs):
    print(f"Title: {title}")
    print(f"Values: {sum(args)}")
    for key, value in kwargs.items():
        print(f"{key}: {value}")

summarize_data("Report", 10, 20, 30, status="Active", priority=1)


# Example 2: استخدام تلميحات النوع وتحديد نوع المعاملات
# Status: verified by running it
# يوضح هذا المثال استخدام تلميحات النوع Type Hinting لتحسين وضوح الكود وتحديد أن width يجب أن يكون معاملًا موضعيًا فقط بفضل الرمز /. يتم حساب المساحة بضرب العرض في الارتفاع الافتراضي أو المعطى. تطبع الدالة النتيجة النهائية وهي 11.0.

def calculate_area(width: float, /, height: float = 10.0) -> float:
    return width * height

result = calculate_area(5.5, height=2.0)
print(f"Area: {result}")
