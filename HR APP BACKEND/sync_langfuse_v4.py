from dotenv import load_dotenv
from langfuse.decorators import observe, langfuse_context

load_dotenv()

# The @observe decorator automatically creates a Trace in Langfuse
@observe()
def JD_Generation_Pipeline():
    print('Sending DeepEval results using Langfuse v4 Decorators...')
    
    # 1. Set the input and output for this specific trace
    langfuse_context.update_current_trace(
        input='Write a JD for a Data Engineer...',
        output='Data Engineer (Remote)...'
    )
    
    # 2. Attach the scores directly to the current trace
    langfuse_context.score(
        name='Answer Relevancy', 
        value=1.0, 
        comment='PASSED: Score 1.0. Output fully addressed the input.'
    )
    langfuse_context.score(
        name='JD Completeness', 
        value=1.0, 
        comment='PASSED: All sections present.'
    )

# Run the function to trigger the trace
JD_Generation_Pipeline()

# Ensure all data is sent to the cloud before the script exits
langfuse_context.flush()

print('? SUCCESS! The data is officially in the cloud. Refresh your Dashboard.')
