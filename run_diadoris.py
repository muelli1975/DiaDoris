import os
os.environ['OPENBLAS_NUM_THREADS']='1'
os.environ['OMP_NUM_THREADS']='1'

if __name__=='__main__':
    from diadoris.app import main
    raise SystemExit(main())
