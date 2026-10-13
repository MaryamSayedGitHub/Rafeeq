# Quiz: Python Functions

1. What is the primary purpose of using *args in a Python function definition?
   A. To enforce a specific number of arguments
   B. To accept a variable number of positional arguments
   C. To define optional keyword arguments
   D. To restrict input to a single data type

2. In the function definition 'def func(a, /, b):', what does the forward slash (/) signify?
   A. Parameter 'a' must be positional-only
   B. Parameter 'a' must be keyword-only
   C. Parameter 'b' must be positional-only
   D. Parameter 'b' must be keyword-only

3. Which syntax correctly uses type hinting for a function that takes an integer and returns a string?
   A. def func(n: int) -> str:
   B. def func(n) -> int: str
   C. def func(n: int, str):
   D. def func(n: str) -> int:

4. What happens if you pass a keyword argument before a positional argument in a standard function call?
   A. The code executes normally
   B. The function ignores the keyword
   C. A SyntaxError is raised
   D. The positional argument is overridden

5. What is the main benefit of modular function design?
   A. Reducing the total lines of code
   B. Increasing execution speed significantly
   C. Improving code reusability and testing
   D. Eliminating the need for global variables

## Answer key

1. B: يسمح المعامل *args بتمرير عدد غير محدد من الوسائط الموضعية إلى الدالة، حيث يتم تجميعها داخل tuple.
2. A: الشرطة المائلة (/) في تعريف الدالة تحدد أن المعاملات التي تسبقها يجب أن تُمرر كموقع (positional-only) فقط.
3. A: تستخدم تلميحات النوع (Type Hinting) النقطتين الرأسيتين لتحديد نوع المدخلات والسهم (->) لتحديد نوع القيمة المرجعة.
4. C: تتطلب قواعد بايثون أن تأتي الوسائط الموضعية قبل الوسائط المسمّاة (keyword arguments) عند استدعاء الدالة.
5. C: التصميم المعياري (Modular design) يجعل الكود أكثر تنظيماً، مما يسهل إعادة استخدامه واختبار كل جزء بشكل منفصل.
