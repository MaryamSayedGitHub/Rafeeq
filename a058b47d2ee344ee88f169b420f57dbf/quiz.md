# Quiz: Python Functions

1. What is the primary purpose of using the slash (/) in a Python function signature?
   A. To force all preceding arguments to be positional-only
   B. To allow arguments to be passed as either keyword or positional
   C. To indicate that the function accepts a variable number of arguments
   D. To mark the end of keyword-only arguments in the signature

2. Given the function definition 'def func(*args, **kwargs):', what does **kwargs represent?
   A. A tuple containing all positional arguments passed
   B. A dictionary containing all keyword arguments passed
   C. A list of mandatory arguments required by the function
   D. A set of unique values passed as keyword arguments

3. Which of the following is the correct syntax for adding type hints to a function parameter?
   A. def greet(name: str) -> None:
   B. def greet(name = str):
   C. def greet(name: 'str'):
   D. def greet(name as str):

4. What is a recommended best practice for modular function design?
   A. Functions should handle multiple unrelated tasks
   B. Functions should rely heavily on global variables
   C. Functions should perform a single, well-defined task
   D. Functions should always print their own results

5. In the signature 'def func(*, key):', what does the asterisk (*) enforce?
   A. The key argument must be passed as a positional argument
   B. The key argument must be passed as a keyword argument
   C. The function can accept any number of positional arguments
   D. The key argument is optional and can be omitted

## Answer key

1. A: تستخدم العلامة (/) في Python لتحديد أن المعاملات التي تسبقها يجب أن تُمرر كمواقع (positional-only) فقط ولا يمكن تمريرها كأسماء مفاتيح.
2. B: يقوم المعامل **kwargs بتجميع كافة المعاملات المسماة (keyword arguments) التي يتم تمريرها للدالة في قاموس (dictionary).
3. A: تستخدم Python النقطتين الرأسيتين (:) لتحديد نوع المعامل، بينما يستخدم السهم (->) لتحديد نوع القيمة التي ترجعها الدالة.
4. C: مبدأ المسؤولية الواحدة (Single Responsibility Principle) ينص على أن الدالة يجب أن تقوم بمهمة واحدة محددة لزيادة قابليتها لإعادة الاستخدام والاختبار.
5. B: تفرض العلامة (*) أن أي معامل يأتي بعدها يجب أن يُمرر كمعامل مسمى (keyword-only argument) حصراً.
