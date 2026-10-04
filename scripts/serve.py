import os
import uvicorn
from config.settings import ROOT

if __name__=='__main__':
    uvicorn.run('backend.main:app',host=os.getenv('HOST','0.0.0.0'),port=int(os.getenv('PORT','8000')),workers=1)
