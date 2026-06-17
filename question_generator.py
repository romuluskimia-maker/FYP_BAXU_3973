"""
Question Generator using Llama 3.2 via Ollama
Generates multiple-choice questions with plausible distractors
"""

import requests
import json
import re
import logging
from typing import List, Dict, Any
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== OLLAMA CONFIGURATION ==========
# Ollama runs locally on port 11434 by default
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"  # or "llama3.2:latest"

# ========== INSTALLATION GUIDE FOR OLLAMA ==========
"""
Install Ollama on your computer:

Windows/Mac:
1. Download from: https://ollama.ai/download
2. Install and run Ollama (it will start in system tray)
3. Open terminal/command prompt and run:
   ollama pull llama3.2
   
Linux:
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3.2

Verify installation:
ollama list  # Should show llama3.2
ollama run llama3.2  # Should open interactive chat

After pulling the model, keep Ollama running in background.
The API will be available at http://localhost:11434
"""

def check_ollama_connection() -> bool:
    """Verify Ollama is running and accessible"""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json()
            logger.info(f"Ollama is running. Available models: {models}")
            return True
    except requests.exceptions.ConnectionError:
        logger.error("Cannot connect to Ollama. Is it running?")
        logger.error("Start Ollama and run: ollama pull llama3.2")
        return False
    return False

def query_llama(prompt: str, temperature: float = 0.7, max_tokens: int = 4000) -> str:
    """
    Send a prompt to Llama 3.2 and get response
    
    Args:
        prompt: The prompt to send to the model
        temperature: Controls randomness (0.0 = deterministic, 1.0 = creative)
        max_tokens: Maximum response length
    
    Returns:
        Model's response text
    """
    if not check_ollama_connection():
        raise Exception("Ollama is not running. Please start Ollama first.")
    
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,  # Get complete response at once
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.9,
        "top_k": 40
    }
    
    try:
        logger.info("Sending request to Llama 3.2...")
        start_time = time.time()
        
        response = requests.post(
            OLLAMA_API_URL,
            json=payload,
            timeout=300  # 5 minute timeout for generation
        )
        
        if response.status_code != 200:
            raise Exception(f"Ollama API error: {response.status_code} - {response.text}")
        
        result = response.json()
        elapsed = time.time() - start_time
        logger.info(f"Response received in {elapsed:.2f} seconds")
        
        return result['response']
    
    except requests.exceptions.Timeout:
        raise Exception("Llama 3.2 took too long to respond. Try reducing text size.")
    except Exception as e:
        logger.error(f"Failed to query Llama: {e}")
        raise

def generate_mcq_with_distractors(text: str, num_questions: int = 5) -> List[Dict[str, Any]]:
    # Truncate text to prevent overwhelming the model
    if len(text) > 3000:
        text = text[:3000] + "\n[Text truncated for processing]"
    """
    Generate multiple choice questions with plausible distractors
    
    Args:
        text: Source text to generate questions from
        num_questions: Number of questions to generate
    
    Returns:
        List of question dictionaries
    """
    # Create the prompt for Llama 3.2
    prompt = f"""You are an expert educational content creator. Based on the following text, generate {num_questions} high-quality multiple choice questions.

Each question must:
1. Test understanding, not just memorization
2. Have 4 options (A, B, C, D)
3. Include plausible distractors that are common misconceptions
4. Have exactly one correct answer
5. Include a brief explanation of why the answer is correct

IMPORTANT: Output ONLY valid JSON in this exact format, no other text:

[
  {{
    "question": "What is the main function of the cell membrane?",
    "options": ["Energy production", "Selective barrier", "Protein synthesis", "Genetic storage"],
    "correct_answer": "B",
    "explanation": "The cell membrane acts as a selective barrier, controlling what enters and exits the cell."
  }},
  {{
    "question": "Another question here?",
    "options": ["Option A", "Option B", "Option C", "Option D"],
    "correct_answer": "C",
    "explanation": "Explanation of why C is correct."
  }}
]

Text to generate questions from:
{text}

Generate {num_questions} thoughtful, challenging questions. Remember: ONLY output valid JSON array, no other text!"""
    
    try:
        # Get response from Llama
        raw_response = query_llama(prompt, temperature=0.7, max_tokens=4000)
        
        # Extract JSON from response (in case LLM adds extra text)
        json_match = re.search(r'\[.*\]', raw_response, re.DOTALL)
        if not json_match:
            raise Exception("Could not find JSON array in response")
        
        json_str = json_match.group(0)
        
        # Parse JSON
        questions = json.loads(json_str)
        
        # Validate and clean questions
        validated_questions = []
        for i, q in enumerate(questions):
            # Ensure all required fields exist
            if not all(k in q for k in ['question', 'options', 'correct_answer']):
                logger.warning(f"Question {i} missing required fields, skipping")
                continue
            
            # Ensure we have exactly 4 options
            if len(q['options']) != 4:
                logger.warning(f"Question {i} has {len(q['options'])} options, adjusting to 4")
                while len(q['options']) < 4:
                    q['options'].append("None of the above")
                q['options'] = q['options'][:4]
            
            # Ensure correct_answer is single letter
            if q['correct_answer'] not in ['A', 'B', 'C', 'D']:
                # Try to convert if it's full text
                correct_text = q['correct_answer']
                for idx, opt in enumerate(q['options']):
                    if opt.lower() == correct_text.lower():
                        q['correct_answer'] = chr(65 + idx)  # A, B, C, D
                        break
                else:
                    q['correct_answer'] = 'A'  # Default to A
            
            # Add explanation if missing
            if 'explanation' not in q:
                q['explanation'] = "No explanation provided."
            
            validated_questions.append(q)
        
        logger.info(f"Successfully generated {len(validated_questions)} questions")
        return validated_questions
    
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        logger.error(f"Raw response: {raw_response[:500]}")
        
        # Fallback: Return a single error question
        return [{
            "question": "Failed to generate questions. Please check the text and try again.",
            "options": ["Check Ollama connection", "Verify text quality", "Reduce text length", "Contact support"],
            "correct_answer": "B",
            "explanation": f"The question generator encountered an error: {str(e)}"
        }]
    
    except Exception as e:
        logger.error(f"Question generation failed: {e}")
        raise

def generate_distractors(question: str, correct_answer: str, context: str = "") -> List[str]:
    """
    Generate better distractors for an existing question
    
    Args:
        question: The question text
        correct_answer: The correct answer text
        context: Optional context from source material
    
    Returns:
        List of 3 distractor options
    """
    prompt = f"""Given this question and correct answer, generate 3 plausible distractors (incorrect but believable answers).

Question: {question}
Correct answer: {correct_answer}
Context: {context if context else "No additional context"}

Generate 3 distractors that are common mistakes or close alternatives.
Output ONLY a JSON array of 3 strings: ["distractor1", "distractor2", "distractor3"]"""
    
    try:
        response = query_llama(prompt, temperature=0.8)
        
        # Extract JSON array
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            distractors = json.loads(match.group(0))
            if len(distractors) >= 3:
                return distractors[:3]
        
        # Fallback distractors
        return ["Option B", "Option C", "Option D"]
    
    except Exception as e:
        logger.error(f"Failed to generate distractors: {e}")
        return ["Option B", "Option C", "Option D"]

def improve_question_quality(question: str, options: List[str], correct: str) -> Dict[str, Any]:
    """
    Ask Llama to improve an existing question's quality
    
    Args:
        question: Original question text
        options: List of 4 options
        correct: Correct answer letter
    
    Returns:
        Improved question dictionary
    """
    prompt = f"""Improve this multiple choice question to be clearer and more educational:

Original question: {question}
Options: A) {options[0]}, B) {options[1]}, C) {options[2]}, D) {options[3]}
Correct answer: {correct}

Output ONLY JSON with improved version:
{{"question": "improved question", "options": ["A", "B", "C", "D"], "explanation": "why the answer is correct"}}"""
    
    try:
        response = query_llama(prompt, temperature=0.5)
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            improved = json.loads(match.group(0))
            return improved
    except Exception as e:
        logger.error(f"Failed to improve question: {e}")
    
    return {"question": question, "options": options, "explanation": ""}

def batch_generate_questions(text_chunks: List[str], questions_per_chunk: int = 3) -> List[Dict[str, Any]]:
    """
    Generate questions from large texts by splitting into chunks
    
    Args:
        text_chunks: List of text chunks
        questions_per_chunk: Questions to generate per chunk
    
    Returns:
        Combined list of questions
    """
    all_questions = []
    
    for i, chunk in enumerate(text_chunks, 1):
        logger.info(f"Processing chunk {i}/{len(text_chunks)}")
        try:
            questions = generate_mcq_with_distractors(chunk, questions_per_chunk)
            all_questions.extend(questions)
            time.sleep(1)  # Rate limiting
        except Exception as e:
            logger.error(f"Failed on chunk {i}: {e}")
            continue
    
    return all_questions

# Test function
def test_llama_connection():
    """Test if Llama 3.2 is working"""
    test_prompt = "Respond with only the word: READY"
    try:
        response = query_llama(test_prompt, temperature=0.0)
        print(f"Llama 3.2 test response: {response}")
        return "READY" in response.upper()
    except Exception as e:
        print(f"Llama test failed: {e}")
        return False

if __name__ == "__main__":
    print("Testing Llama 3.2 connection...")
    if test_llama_connection():
        print("✓ Llama 3.2 is working!")
        
        # Test question generation
        test_text = "The mitochondria is the powerhouse of the cell. It generates ATP through cellular respiration."
        print("\nGenerating test question...")
        questions = generate_mcq_with_distractors(test_text, 1)
        print(json.dumps(questions, indent=2))
    else:
        print("✗ Llama 3.2 not accessible. Please:")
        print("1. Install Ollama from https://ollama.ai")
        print("2. Run: ollama pull llama3.2")
        print("3. Keep Ollama running in background")