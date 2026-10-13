# Example 1: استخدام الوسائط الموضعية والكلمات المفتاحية مع تلميحات النوع
# Status: verified by running it
# يوضح هذا المثال كيفية استخدام العلامة النجمية لفرض استخدام الكلمات المفتاحية للوسائط اللاحقة، مع إضافة تلميحات النوع لتحسين جودة الكود. يتم تحديد العرض والارتفاع كقيم موضعية، بينما يجب تحديد الوحدة ككلمة مفتاحية. يطبع الكود مساحة المستطيل مع الوحدة المحددة، أو الوحدة الافتراضية إذا لم يتم توفيرها.

def calculate_area(width: float, height: float, *, unit: str = 'cm') -> float:
    area = width * height
    print(f'Area: {area} {unit}')
    return area

calculate_area(10.0, 5.0, unit='meters')
calculate_area(2.0, 3.0)


# Example 2: التعامل مع الوسائط المرنة باستخدام args و kwargs
# Status: verified by running it
# يستخدم هذا المثال args لجمع عدد غير محدود من الأرقام و kwargs لجمع أي وسائط إضافية كقاموس. تقوم الدالة بحساب مجموع الأرقام الممررة وطباعة العنوان مع تفاصيل إضافية من القاموس. يطبع الكود عنوان التقرير، مجموع الأرقام، واسم المؤلف مع الحالة.

def summarize_data(title: str, *args: int, **kwargs: str) -> None:
    total = sum(args)
    print(f'Title: {title}')
    print(f'Sum: {total}')
    for key, value in kwargs.items():
        print(f'{key}: {value}')

summarize_data('Sales Report', 10, 20, 30, author='Alice', status='Final')
